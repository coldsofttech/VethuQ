import pytest
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.settings import UpdateSettings
from vethuq_core.storage import open_storage

runner = CliRunner()


@pytest.fixture(autouse=True)
def _db(use_temp_db, monkeypatch):
    use_temp_db()
    monkeypatch.delenv("VETHUQ_UPDATE_CHECK", raising=False)


def stored(read):
    storage = open_storage()
    try:
        return read(storage)
    finally:
        storage.close()


class TestCheck:
    def test_on_by_default(self):
        out = runner.invoke(app, ["settings", "updates", "check", "show"])

        assert out.exit_code == 0 and "on" in out.output

    @pytest.mark.parametrize("value", ["on", "notify-only", "off"])
    def test_set(self, value):
        out = runner.invoke(app, ["settings", "updates", "check", "set", value])

        assert out.exit_code == 0, out.output
        assert stored(UpdateSettings.get_check) == value

    def test_rejects_other_values(self):
        out = runner.invoke(app, ["settings", "updates", "check", "set", "maybe"])

        assert out.exit_code == 1 and "must be one of" in out.output

    def test_reset(self):
        runner.invoke(app, ["settings", "updates", "check", "set", "off"])

        out = runner.invoke(app, ["settings", "updates", "check", "reset"])

        assert out.exit_code == 0 and stored(UpdateSettings.get_check) == "on"

    def test_show_mentions_the_environment_variable(self, monkeypatch):
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", "off")

        out = runner.invoke(app, ["settings", "updates", "check", "show"])

        assert "VETHUQ_UPDATE_CHECK" in out.output


class TestSnooze:
    def test_set_show_clear(self):
        assert "not snoozed" in runner.invoke(app, ["settings", "updates", "snooze", "show"]).output

        assert runner.invoke(app, ["settings", "updates", "snooze", "set", "3"]).exit_code == 0
        assert stored(UpdateSettings.is_snoozed) is True
        assert (
            "snoozed until" in runner.invoke(app, ["settings", "updates", "snooze", "show"]).output
        )

        assert runner.invoke(app, ["settings", "updates", "snooze", "clear"]).exit_code == 0
        assert stored(UpdateSettings.is_snoozed) is False

    def test_default_is_one_day(self):
        runner.invoke(app, ["settings", "updates", "snooze", "set"])

        assert stored(UpdateSettings.is_snoozed) is True

    def test_days_must_be_positive(self):
        out = runner.invoke(app, ["settings", "updates", "snooze", "set", "0"])

        assert out.exit_code == 1 and "greater than 0" in out.output


class TestSkip:
    def test_set_show_clear(self):
        assert "No version" in runner.invoke(app, ["settings", "updates", "skip", "show"]).output

        assert runner.invoke(app, ["settings", "updates", "skip", "set", "1.2.0"]).exit_code == 0
        assert stored(UpdateSettings.get_skipped_version) == "1.2.0"
        assert "1.2.0" in runner.invoke(app, ["settings", "updates", "skip", "show"]).output

        assert runner.invoke(app, ["settings", "updates", "skip", "clear"]).exit_code == 0
        assert stored(UpdateSettings.get_skipped_version) is None
