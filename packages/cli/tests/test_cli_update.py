from __future__ import annotations

import io
from types import SimpleNamespace

from vethuq_cli.notices import AfterCommand

from vethuq.enums import UpdateStatus


class _Tty(io.StringIO):
    def isatty(self):
        return True


def _client(
    status=UpdateStatus.AVAILABLE,
    notify=True,
    message="VethuQ 2.0.0 is available.",
    notices=(),
    trust="",
):
    result = SimpleNamespace(status=status, notify=notify, message=message)
    return SimpleNamespace(
        updates=SimpleNamespace(status=lambda: result),
        policy=SimpleNamespace(
            notices=lambda: tuple(notices),
            current=lambda: SimpleNamespace(trust_message=trust),
        ),
    )


def _notice(severity="info", message="Hello", link=None):
    return SimpleNamespace(severity=severity, message=message, link=link)


class TestWhenToPrint:
    def test_piped_output_is_never_touched(self):
        assert not AfterCommand.wanted(["source", "list"], stdout=io.StringIO(), stderr=_Tty())
        assert not AfterCommand.wanted(["source", "list"], stdout=_Tty(), stderr=io.StringIO())

    def test_a_terminal_gets_it(self):
        assert AfterCommand.wanted(["source", "list"], stdout=_Tty(), stderr=_Tty())

    def test_json_help_version_and_the_update_commands_do_not(self):
        for argv in (
            ["--json", "source", "list"],
            ["--help"],
            ["--version"],
            ["update"],
            ["updates", "check"],
            ["policy", "show"],
            [],
        ):
            assert not AfterCommand.wanted(argv, stdout=_Tty(), stderr=_Tty()), argv


class TestLines:
    def test_an_available_update_points_to_vethuq_update(self):
        ((text, _),) = AfterCommand.lines(_client())

        assert "2.0.0 is available" in text and text.endswith("Run: vethuq update")

    def test_nothing_to_say_prints_nothing(self):
        assert AfterCommand.lines(_client(UpdateStatus.UP_TO_DATE, notify=False, message="")) == []

    def test_a_disabled_check_prints_nothing_at_all(self):
        client = _client(UpdateStatus.DISABLED, notify=False, message="", notices=[_notice()])
        assert AfterCommand.lines(client) == []

    def test_notices_show_severity_and_link(self):
        client = _client(
            UpdateStatus.UP_TO_DATE,
            notify=False,
            message="",
            notices=[_notice(), _notice("critical", "Stop", "https://x")],
        )

        texts = [t for t, _ in AfterCommand.lines(client)]

        assert texts == ["Hello", "CRITICAL: Stop (https://x)"]

    def test_a_revoked_signing_key_is_said_once_even_with_nothing_else_to_say(self):
        client = _client(
            UpdateStatus.UP_TO_DATE, notify=False, message="", trust="The signing key was revoked."
        )

        assert [t for t, _ in AfterCommand.lines(client)] == ["The signing key was revoked."]

    def test_a_failure_prints_nothing(self):
        broken = SimpleNamespace(updates=SimpleNamespace(status=lambda: 1 / 0))
        assert AfterCommand.lines(broken) == []


class TestCommands:
    def test_update_prints_the_steps(self, run):
        result = run("update", "--no-check")

        assert result.exit_code == 0, result.output
        assert (
            "Installed as:" in result.output
            and "Then start VethuQ again." in result.output
            or ("installer" in result.output)
        )

    def test_update_json_has_the_install_type_and_commands(self, run_json):
        data = run_json("update", "--no-check")

        assert {"install_type", "steps", "commands", "status"} <= set(data)

    def test_policy_notices_with_no_policy(self, run):
        result = run("policy", "notices")

        assert result.exit_code == 0 and "No notices." in result.output
