"""`vethuq source ...` commands for registering files and folders as sources."""

from __future__ import annotations

import typer
from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.sources import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    SourcePathError,
    Sources,
)
from vethuq_core.storage import open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Manage files and folders registered as VethuQ sources.")

_STATUS_STYLES = {"indexed": Theme.SUCCESS, "pending": Theme.PRIMARY, "error": Theme.DANGER}


class SourcePanel:
    @staticmethod
    def build(message: str | Text | Table, border_style: str) -> Panel:
        """A full-width "Sources" panel: `message` (white unless already styled), left-aligned
        title, coloured border."""
        content: RenderableType
        if isinstance(message, Table):
            content = message
        else:
            content = Text(message, style="white") if isinstance(message, str) else message
            # The shared console is soft-wrapping, which would crop long lines in a panel.
            content.no_wrap = False
            content.overflow = "fold"
        return Panel(
            content,
            title="Sources",
            title_align="left",
            border_style=border_style,
            expand=True,
        )


@app.command("add")
def add(
    path: str = typer.Argument(
        ..., help="File or folder to register. Folders are indexed recursively."
    ),
) -> None:
    """Register a file or folder as a VethuQ source."""
    storage = open_storage()
    try:
        source = Sources.add(storage, path)
    except (SourcePathError, SourceAlreadyExistsError) as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc
    else:
        console.print(
            SourcePanel.build(
                Text.assemble(
                    (f"Added {source.source_type}: ", Theme.OK),
                    (source.path, "white"),
                    ("\n\nRun '", "white"),
                    ("vethuq index run", Theme.COMMAND),
                    ("' to process pending sources.", "white"),
                ),
                Theme.OK,
            )
        )
    finally:
        storage.close()


@app.command("list")
def list_() -> None:
    """List registered sources."""
    storage = open_storage()
    try:
        sources = Sources.list_all(storage)
    finally:
        storage.close()

    if not sources:
        console.print(SourcePanel.build("No sources registered yet.", "bright_black"))
        return

    table = Table(box=box.SIMPLE, header_style=f"bold {Theme.PRIMARY}", border_style=Theme.PRIMARY)
    table.add_column("ID", justify="right", style="bright_black")
    table.add_column("Type", style=Theme.LABEL)
    table.add_column("Status")
    # The shared console is soft-wrapping, which would crop a long path.
    table.add_column("Path", no_wrap=False, overflow="fold")
    for source in sources:
        table.add_row(
            str(source.id),
            source.source_type,
            Text(source.status, style=_STATUS_STYLES.get(source.status, "default")),
            source.path,
        )
    console.print(SourcePanel.build(table, Theme.PRIMARY))


@app.command("remove")
def remove(
    path_or_id: str = typer.Argument(..., help="Registered source id or path to remove."),
    force: bool = typer.Option(False, "--force", help="Remove without asking for confirmation."),
) -> None:
    """Remove a registered source."""
    storage = open_storage()
    try:
        target = Sources.coerce(path_or_id)
        try:
            source = Sources.get(storage, target)
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style=Theme.ERROR)
            raise typer.Exit(code=1) from exc

        if not force:
            prompt = Text.assemble(
                "Remove ", (source.source_type, Theme.LABEL), f" '{source.path}'?"
            )
            if not Confirm.ask(prompt, console=console, default=False):
                console.print(SourcePanel.build("Aborted.", "bright_black"))
                raise typer.Exit(code=0)

        source = Sources.remove(storage, target)
    finally:
        storage.close()

    console.print(
        SourcePanel.build(
            Text.assemble((f"Removed {source.source_type}: ", Theme.OK), (source.path, "white")),
            Theme.OK,
        )
    )
