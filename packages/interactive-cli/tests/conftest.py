from __future__ import annotations

import pytest
import typer
from vethuq_cli.main import build_app
from vethuq_cli.state import State
from vethuq_interactive_cli.shell import Shell
from vethuq_interactive_cli.ui import Quit


class ScriptedUi:
    """Answers the shell's questions from a list: a key for a select, text for a text, True/False
    for a confirm. When the script runs out the shell is told to quit."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked: list[tuple[str, object]] = []

    def _next(self, kind, prompt, extra=None):
        self.asked.append((kind, prompt, extra))
        if not self.answers:
            raise Quit
        return self.answers.pop(0)

    def select(self, title, choices):
        answer = self._next("select", title, [key for key, _ in choices])
        return answer

    def text(self, prompt, default=""):
        answer = self._next("text", prompt, default)
        return default if answer is None else answer

    def confirm(self, prompt, default=False):
        answer = self._next("confirm", prompt, default)
        return default if answer is None else answer


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VETHUQ_HOME", str(tmp_path / "home"))
    State.reset()
    State.db_path = tmp_path / "db" / "vethuq.db"
    yield
    State.reset()


@pytest.fixture
def shell():
    """`shell(answers)` runs the shell on a script and returns the UI (to see what was asked)."""

    def build(*answers):
        ui = ScriptedUi(answers)
        root = typer.main.get_command(build_app())
        Shell(ui, root).run()
        return ui

    return build


@pytest.fixture
def docs(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text("hello museum world")
    return folder


@pytest.fixture
def scripted_ui():
    """The `ScriptedUi` class, for tests that build their own command tree."""
    return ScriptedUi
