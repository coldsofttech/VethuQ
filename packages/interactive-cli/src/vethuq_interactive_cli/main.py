"""Starting the shell."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer
from vethuq_cli.main import build_app
from vethuq_cli.state import State

from vethuq_interactive_cli.shell import Shell
from vethuq_interactive_cli.ui import QuestionaryUi, Ui


def run(ui: Ui | None = None, db: Path | None = None, root: Any = None) -> None:
    """Open the interactive shell (arrow-key menus over the `vethuq` commands)."""
    if db is not None:
        State.db_path = db
    if root is None:
        root = typer.main.get_command(build_app())  # type: ignore[assignment]
    Shell(ui or QuestionaryUi(), root).run()  # type: ignore[arg-type]


def interactive_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def main() -> None:
    """The `vethuq-interactive` script."""
    argv = sys.argv[1:]
    db = (
        Path(argv[argv.index("--db") + 1])
        if "--db" in argv and argv.index("--db") + 1 < len(argv)
        else None
    )
    run(db=db)
