import json

import pytest
from typer.testing import CliRunner
from vethuq_cli.main import Cli, app
from vethuq_cli.updates import UpdateNotice
from vethuq_core.policy import PolicyService
from vethuq_core.updates import UpdateChecker, UpdateResult, UpdateStatus

runner = CliRunner()


def result(status=UpdateStatus.AVAILABLE, **fields):
    base = {
        "mode": "on",
        "current": "1.0.0",
        "distribution": "pip",
        "latest": "1.2.0",
        "minimum_supported": "1.0.0",
    }
    return UpdateResult(status, **{**base, **fields})


@pytest.fixture(autouse=True)
def _isolated(use_temp_db, monkeypatch):
    use_temp_db()
    PolicyService.reset()
    monkeypatch.delenv("VETHUQ_UPDATE_CHECK", raising=False)
    yield
    PolicyService.reset()


def fake_status(monkeypatch, found):
    monkeypatch.setattr(UpdateChecker, "status", staticmethod(lambda *a, **k: found))


class TestUpdatesCommands:
    def test_status_without_a_signed_policy_is_unknown(self):
        out = runner.invoke(app, ["updates", "status"])

        assert out.exit_code == 0, out.output
        assert "unknown" in out.output

    def test_status_shows_versions_and_notes(self, monkeypatch):
        fake_status(monkeypatch, result(release_notes_url="https://example.com/notes"))

        out = runner.invoke(app, ["updates", "status"])

        assert "1.2.0" in out.output and "https://example.com/notes" in out.output
        assert "newer version is available" in out.output

    def test_status_json(self, monkeypatch):
        fake_status(monkeypatch, result())

        data = json.loads(runner.invoke(app, ["updates", "status", "--json"]).output)

        assert data["status"] == "available" and data["notify"] is True
        assert data["latest"] == "1.2.0"

    def test_status_says_when_the_environment_turned_it_off(self, monkeypatch):
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", "off")

        out = runner.invoke(app, ["updates", "status"])

        assert "VETHUQ_UPDATE_CHECK" in out.output and "off" in out.output

    def test_check_forces_a_refresh(self, monkeypatch):
        seen = {}

        def fake_check(storage, force=False, logger=None):
            seen["force"] = force
            return result(UpdateStatus.UP_TO_DATE, current="1.2.0")

        monkeypatch.setattr(UpdateChecker, "check", staticmethod(fake_check))

        out = runner.invoke(app, ["updates", "check"])

        assert out.exit_code == 0 and seen["force"] is True
        assert "up to date" in out.output


class TestNotice:
    @pytest.fixture
    def tty(self, monkeypatch):
        monkeypatch.setattr(UpdateNotice, "is_terminal", staticmethod(lambda: True))

    def printed(self, capsys, args=()):
        UpdateNotice.show(list(args))
        return capsys.readouterr().out

    def test_one_line_when_a_newer_version_exists(self, tty, monkeypatch, capsys):
        fake_status(monkeypatch, result())

        text = self.printed(capsys, ["source", "list"])

        assert "1.2.0 is available" in text and "vethuq updates status" in text

    def test_nothing_when_piped(self, monkeypatch, capsys):
        fake_status(monkeypatch, result())

        assert self.printed(capsys) == ""

    @pytest.mark.parametrize(
        "found",
        [
            result(UpdateStatus.UP_TO_DATE, current="1.2.0"),
            result(UpdateStatus.DISABLED),
            result(snoozed=True),
            result(skipped=True),
            result(UpdateStatus.UNKNOWN, latest=None),
        ],
    )
    def test_nothing_to_say(self, tty, monkeypatch, capsys, found):
        fake_status(monkeypatch, found)

        assert self.printed(capsys) == ""

    @pytest.mark.parametrize(
        "args", [["updates", "status"], ["background-service", "status", "--json"], ["--help"]]
    )
    def test_quiet_for_the_updates_command_json_and_help(self, tty, monkeypatch, capsys, args):
        fake_status(monkeypatch, result())

        assert self.printed(capsys, args) == ""

    def test_below_minimum_is_mentioned_even_when_snoozed(self, tty, monkeypatch, capsys):
        fake_status(
            monkeypatch, result(UpdateStatus.BELOW_MINIMUM, minimum_supported="1.1.0", snoozed=True)
        )

        assert "minimum supported" in self.printed(capsys)

    def test_never_fails_a_command(self, tty, monkeypatch, capsys):
        def boom(*a, **k):
            raise RuntimeError("broken")

        monkeypatch.setattr(UpdateChecker, "status", staticmethod(boom))

        assert self.printed(capsys) == ""

    def test_shown_after_a_successful_command(self, monkeypatch):
        shown = []
        monkeypatch.setattr(UpdateNotice, "show", staticmethod(lambda args: shown.append(args)))
        monkeypatch.setattr("sys.argv", ["vethuq", "policy", "show"])

        with pytest.raises(SystemExit):
            Cli.run()

        assert shown == [["policy", "show"]]

    def test_not_shown_after_a_failed_command(self, monkeypatch):
        shown = []
        monkeypatch.setattr(UpdateNotice, "show", staticmethod(lambda args: shown.append(args)))
        monkeypatch.setattr("sys.argv", ["vethuq", "no-such-command"])

        with pytest.raises(SystemExit):
            Cli.run()

        assert shown == []
