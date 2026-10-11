"""How the shell asks questions: arrow-key menus and prompts (questionary), behind a small
interface so the shell can be driven by a script in tests."""

from __future__ import annotations

from typing import Protocol


class Quit(Exception):  # noqa: N818 - control flow, not an error
    """Leave the whole shell (Ctrl-C or Ctrl-D at any question)."""


class Ui(Protocol):
    def select(self, title: str, choices: list[tuple[str, str]]) -> str:
        """Pick one of `(key, label)`; returns the key. Raises `Quit` on Ctrl-C."""

    def text(self, prompt: str, default: str = "") -> str:
        """A line of text (the default when empty). Raises `Quit` on Ctrl-C."""

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """Yes or no. Raises `Quit` on Ctrl-C."""


class QuestionaryUi:
    """Arrow keys to move, Enter to choose, Ctrl-C to leave. `input`/`output` are for tests."""

    def __init__(self, input: object | None = None, output: object | None = None) -> None:  # noqa: A002
        self._io = {k: v for k, v in (("input", input), ("output", output)) if v is not None}

    @staticmethod
    def _answer(value: object) -> object:
        if value is None:  # questionary answers None on Ctrl-C / Ctrl-D
            raise Quit
        return value

    def select(self, title: str, choices: list[tuple[str, str]]) -> str:
        import questionary

        options = [questionary.Choice(title=label, value=key) for key, label in choices]
        return str(
            self._answer(
                questionary.select(
                    title,
                    options,
                    instruction="(arrows to move, Enter to choose, Ctrl-C to quit)",
                    **self._io,
                ).ask()
            )
        )

    def text(self, prompt: str, default: str = "") -> str:
        import questionary

        return str(self._answer(questionary.text(prompt, default=default, **self._io).ask()))

    def confirm(self, prompt: str, default: bool = False) -> bool:
        import questionary

        return bool(self._answer(questionary.confirm(prompt, default=default, **self._io).ask()))
