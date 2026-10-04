"""`vethuq file-types ...` commands: which file types this install can read."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.filetypes import FileType, FileTypes
from vethuq_core.settings.filetypes import FileTypeSettings
from vethuq_core.storage import open_storage

from vethuq_cli.console import console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Show which file types are installed.")


class TypesTable:
    @staticmethod
    def status(file_type: FileType) -> Text:
        if not file_type.is_installed():
            return Text("not installed", style=Theme.WARNING)
        if not FileTypes.is_enabled(file_type):
            return Text("installed, not enabled", style=Theme.NOTICE)
        return Text("installed", style=Theme.OK)

    @staticmethod
    def build(file_types: list[FileType], *, show_hints: bool) -> Table:
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("Type", "Extensions", "Package", "Status"):
            table.add_column(column)
        if show_hints:
            table.add_column("Install")
        for file_type in file_types:
            row = [
                Text(file_type.label, style="bold"),
                Text(", ".join(file_type.extensions), style="white"),
                Text(file_type.extra, style="white"),
                TypesTable.status(file_type),
            ]
            if show_hints:
                row.append(
                    Text("" if file_type.is_installed() else file_type.install_hint, style="white")
                )
            table.add_row(*row)
        return table


@app.command("list")
def list_types(
    all_types: bool = typer.Option(
        False,
        "--all",
        help="Also list file types that are not installed, with the command to install each.",
    ),
) -> None:
    """List the installed file types.

    Installing or removing a type is done with pip (`pip install vethuq[type-eml]`) or by
    re-running the installer - there is no enable/disable switch here.
    """
    file_types = list(FileTypes.all() if all_types else FileTypes.installed())
    # Keep the database's record of installed types current.
    storage = open_storage()
    try:
        FileTypeSettings.record_installed(storage)
    finally:
        storage.close()
    if not file_types:
        console.print(Text("No file types are installed.", style=Theme.NOTICE))
        return
    console.print(
        Panel(
            TypesTable.build(file_types, show_hints=all_types),
            title=Text("File types"),
            title_align="left",
            border_style=Theme.PRIMARY,
            expand=True,
        )
    )
