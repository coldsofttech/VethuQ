"""`vethuq source ...` commands for registering files and folders as sources."""

from __future__ import annotations

import typer
from rich.prompt import Confirm
from rich.text import Text
from vethuq_core.db import connect
from vethuq_core.sources import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    SourcePathError,
    add_source,
    get_source,
    list_sources,
    remove_source,
)

from vethuq_cli.console import console, error_console

app = typer.Typer(help="Manage files and folders registered as VethuQ sources.")

_STATUS_STYLES = {"indexed": "green", "pending": "blue", "error": "red"}


@app.command("add")
def add(
    path: str = typer.Argument(
        ..., help="File or folder to register. Folders are indexed recursively."
    ),
) -> None:
    """Register a file or folder as a VethuQ source."""
    conn = connect()
    try:
        source = add_source(conn, path)
    except (SourcePathError, SourceAlreadyExistsError) as exc:
        error_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc
    else:
        console.print(Text.assemble((f"Added {source.source_type}: ", "bold green"), source.path))
        console.print()
        console.print(
            Text.assemble(
                "Run '", ("vethuq index run", "bold cyan"), "' to process pending sources."
            )
        )
    finally:
        conn.close()


@app.command("list")
def list_() -> None:
    """List registered sources."""
    conn = connect()
    try:
        sources = list_sources(conn)
    finally:
        conn.close()

    if not sources:
        console.print("No sources registered yet.", style="bright_black")
        return

    for source in sources:
        line = Text.assemble(
            "[",
            (str(source.id), "bright_black"),
            "] ",
            (f"{source.source_type:<6}", "bright_yellow"),
            " ",
            (f"{source.status:<8}", _STATUS_STYLES.get(source.status, "default")),
            f" {source.path}",
        )
        console.print(line)


@app.command("remove")
def remove(
    path_or_id: str = typer.Argument(..., help="Registered source id or path to remove."),
    force: bool = typer.Option(False, "--force", help="Remove without asking for confirmation."),
) -> None:
    """Remove a registered source."""
    conn = connect()
    try:
        target: str | int = int(path_or_id) if path_or_id.isdigit() else path_or_id
        try:
            source = get_source(conn, target)
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style="bold red")
            raise typer.Exit(code=1) from exc

        if not force:
            prompt = Text.assemble(
                "Remove ", (source.source_type, "bright_yellow"), f" '{source.path}'?"
            )
            if not Confirm.ask(prompt, console=console, default=False):
                console.print("Aborted.", style="bright_black")
                raise typer.Exit(code=0)

        source = remove_source(conn, target)
    finally:
        conn.close()

    console.print(Text.assemble((f"Removed {source.source_type}: ", "bold green"), source.path))
