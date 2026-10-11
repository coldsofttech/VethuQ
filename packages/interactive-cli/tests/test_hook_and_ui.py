from __future__ import annotations

import vethuq_interactive_cli
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner
from vethuq_cli.main import build_app
from vethuq_cli.state import State
from vethuq_interactive_cli.ui import QuestionaryUi


def test_no_command_on_a_terminal_opens_the_shell(monkeypatch):
    opened = []
    monkeypatch.setattr("vethuq_cli.main._can_interact", lambda: True)
    monkeypatch.setattr(vethuq_interactive_cli, "run", lambda root=None, **k: opened.append(root))
    result = CliRunner().invoke(build_app(), [])
    assert result.exit_code == 0 and len(opened) == 1


def test_no_command_off_a_terminal_prints_help():
    result = CliRunner().invoke(build_app(), [])
    assert "Usage" in result.output


def test_the_interactive_flag_forces_the_shell(monkeypatch):
    opened = []
    monkeypatch.setattr(vethuq_interactive_cli, "run", lambda root=None, **k: opened.append(1))
    CliRunner().invoke(build_app(), ["--interactive"])
    assert opened == [1]


def test_a_command_is_never_interactive(monkeypatch):
    monkeypatch.setattr("vethuq_cli.main._can_interact", lambda: True)
    monkeypatch.setattr(
        vethuq_interactive_cli, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )
    assert CliRunner().invoke(build_app(), ["version"]).exit_code == 0


def test_arrow_keys_move_and_enter_chooses():
    with create_pipe_input() as pipe:
        pipe.send_text("\x1b[B\r")  # down, enter
        ui = QuestionaryUi(input=pipe, output=DummyOutput())
        assert ui.select("Pick", [("a", "A"), ("b", "B"), ("c", "C")]) == "b"


def test_text_and_confirm_prompts():
    with create_pipe_input() as pipe:
        pipe.send_text("hello\r")
        assert QuestionaryUi(input=pipe, output=DummyOutput()).text("Say") == "hello"
    with create_pipe_input() as pipe:
        pipe.send_text("y\r")
        assert QuestionaryUi(input=pipe, output=DummyOutput()).confirm("Sure?") is True


_ = State
