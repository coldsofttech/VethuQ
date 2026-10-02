"""`vethuq db ...` database maintenance commands."""

from __future__ import annotations

import typer
from vethuq_core.db import Db
from vethuq_core.db.integrity import IntegrityCheck

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Database maintenance commands.")


@app.command("integrity-check")
def integrity_check() -> None:
    """Run `PRAGMA integrity_check` now and print the result.

    Also logged via the standard `logging` module (info on success, error
    with the specific corruption messages on failure). See 'vethuq settings
    db integrity-check' to control whether this also runs automatically
    when the database is opened.
    """
    conn = Db.connect()
    try:
        result = IntegrityCheck.run(conn)
    finally:
        conn.close()

    if result.ok:
        console.print("Database integrity check passed.", style=Theme.OK)
        return

    error_console.print("Database integrity check FAILED:", style=Theme.ERROR)
    for message in result.errors:
        error_console.print(f"  {message}", style=Theme.ERROR)
    raise typer.Exit(code=1)
