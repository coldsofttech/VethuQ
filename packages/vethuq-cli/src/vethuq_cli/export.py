"""`--export` and `--format` for the listing commands: write the list to a JSON or HTML file."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.text import Text
from vethuq_core.search import Export
from vethuq_core.settings import InvalidSettingValueError, SearchSettings
from vethuq_core.storage import Storage, open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme


class ListExport:
    """The shared options, and writing a listing's records through `Export.records`."""

    EXPORT = Annotated[
        str | None,
        typer.Option(
            "--export",
            help=(
                "Write the listing to this file instead of printing it. The format defaults to "
                "`vethuq settings search export-format` unless --format overrides it."
            ),
        ),
    ]
    FORMAT = Annotated[
        str | None,
        typer.Option("--format", help="Export format: 'json' or 'html'. Only used with --export."),
    ]

    @staticmethod
    def resolve(
        export: str | None, format_: str | None, storage: Storage | None = None
    ) -> tuple[Path, str] | None:
        """The `(output path, format)` to export to, or None if `--export` wasn't given."""
        if export is None:
            if format_ is not None:
                error_console.print("--format needs --export.", style=Theme.ERROR)
                raise typer.Exit(code=1)
            return None
        owned = storage is None
        storage = storage or open_storage()
        try:
            return Path(export), SearchSettings.resolve_export_format(storage, format_)
        except InvalidSettingValueError as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        finally:
            if owned:
                storage.close()

    @staticmethod
    def report(count: int, noun: str, output: Path, format_: str) -> None:
        console.print(
            Text.assemble(
                "Exported ", (str(count), Theme.VALUE), f" {noun} to {output} ({format_})."
            )
        )

    @staticmethod
    def write(
        target: tuple[Path, str],
        records: list[dict[str, object]],
        columns: list[tuple[str, str]],
        *,
        title: str,
        key: str,
        noun: str,
        **options,
    ) -> None:
        """Write `records` to `target` (from `resolve`) and say so."""
        output, format_ = target
        Export.records(records, columns, output, format_, title=title, key=key, **options)
        ListExport.report(len(records), noun, output, format_)
