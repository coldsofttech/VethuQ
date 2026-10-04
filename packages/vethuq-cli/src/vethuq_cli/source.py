"""`vethuq source ...` commands for registering files and folders as sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.formatting import Formatting
from vethuq_core.ocr import Deepening
from vethuq_core.search import Export
from vethuq_core.settings import InvalidSettingValueError, SearchSettings
from vethuq_core.sources import (
    Source,
    SourceAlreadyExistsError,
    SourceFile,
    SourceNotFoundError,
    SourceNotRemovedError,
    SourcePathError,
    Sources,
    SourceSort,
)
from vethuq_core.storage import open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Manage files and folders registered as VethuQ sources.")

_STATUS_STYLES = {"indexed": Theme.SUCCESS, "pending": Theme.PRIMARY, "error": Theme.DANGER}
_FILE_STATUS_STYLES = {
    "indexed": Theme.SUCCESS,
    "pending": Theme.PRIMARY,
    "processing": Theme.PRIMARY,
    "error": Theme.DANGER,
    "removed": "bright_black",
    "unsupported": Theme.WARNING,
}


class SourcePanel:
    @staticmethod
    def build(message: str | Text | Table, border_style: str, title: str = "Sources") -> Panel:
        """A full-width panel (titled "Sources" by default): `message` (white unless already
        styled), left-aligned title, coloured border."""
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
            title=Text(title),
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


class SourceFiles:
    """Rendering of the files under a source: a table, or a panel per file with `--detail`."""

    @staticmethod
    def _status(file: SourceFile) -> Text:
        return Text(file.status, style=_FILE_STATUS_STYLES.get(file.status, "default"))

    @staticmethod
    def table(source: Source, files: list[SourceFile]) -> Panel:
        table = Table(
            box=box.SIMPLE, header_style=f"bold {Theme.PRIMARY}", border_style=Theme.PRIMARY
        )
        table.add_column("ID", justify="right", style="bright_black", no_wrap=True)
        # The shared console is soft-wrapping, which would crop a long path.
        table.add_column("File", no_wrap=False, overflow="fold")
        table.add_column("Status", no_wrap=True)
        for file in files:
            table.add_row(
                str(file.id), SourceSort.file_name(source, file), SourceFiles._status(file)
            )
        return SourcePanel.build(table, Theme.PRIMARY, title=f"Sources / {source.path}")

    @staticmethod
    def detail(source: Source, file: SourceFile, max_phase: int) -> Panel:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style=Theme.LABEL, no_wrap=True)
        grid.add_column(no_wrap=False, overflow="fold")

        grid.add_row("Status", SourceFiles._status(file))
        grid.add_row("Type", file.file_type)
        grid.add_row("Size", Formatting.size(file.file_size_bytes))
        grid.add_row("Pages", str(file.pages) if file.pages else "-")
        grid.add_row("Started", Formatting.timestamp(file.started_at))
        grid.add_row("Completed", Formatting.timestamp(file.completed_at))
        grid.add_row("Indexed", Formatting.timestamp(file.indexed_at))
        grid.add_row("Duration", Formatting.seconds(file.duration))
        if file.confidence is not None:
            grid.add_row("Confidence", f"{file.confidence:.0%}")
        if file.ocr_phase is not None:
            name = Deepening.PHASE_NAMES.get(file.ocr_phase, str(file.ocr_phase))
            grid.add_row("OCR phase", f"{name} ({file.ocr_phase}/{max_phase})")
            grid.add_row("OCR angles", ", ".join(f"{a}°" for a in file.ocr_angles))
        for timing in file.phase_timings:
            name = Deepening.PHASE_NAMES.get(timing.phase, str(timing.phase)).capitalize()
            grid.add_row(
                f"{name} phase",
                f"started {Formatting.timestamp(timing.started_at)}, "
                f"completed {Formatting.timestamp(timing.completed_at)}, "
                f"took {Formatting.seconds(timing.duration_seconds)}",
            )
        if file.retry_count:
            grid.add_row("Retries", str(file.retry_count))
        if file.duplicate_of_path:
            grid.add_row("Duplicate of", file.duplicate_of_path)
        if file.error_message:
            grid.add_row("Error", Text(file.error_message, style=Theme.ERROR))

        title = f"Sources / [{file.id}] {SourceSort.file_name(source, file)}"
        return SourcePanel.build(grid, Theme.PRIMARY, title=title)


def _resolve_export(storage, export: str | None, format_: str | None) -> tuple[Path, str] | None:
    """The `(output path, format)` to export to, or None if `--export` wasn't given."""
    if export is None:
        if format_ is not None:
            error_console.print("--format needs --export.", style=Theme.ERROR)
            raise typer.Exit(code=1)
        return None
    try:
        return Path(export), SearchSettings.resolve_export_format(storage, format_)
    except InvalidSettingValueError as exc:
        error_console.print(f"Error: {exc}", style=Theme.ERROR)
        raise typer.Exit(code=1) from exc


def _report_export(count: int, noun: str, output: Path, format_: str) -> None:
    console.print(
        Text.assemble("Exported ", (str(count), Theme.VALUE), f" {noun} to {output} ({format_}).")
    )


@app.command("list")
def list_(
    target: str | None = typer.Argument(
        None, help="List the files under this source id or path instead of the sources."
    ),
    detail: bool = typer.Option(
        False,
        "--detail",
        help="With a source: also show timestamps, OCR phases, and other per-file detail.",
    ),
    export: str | None = typer.Option(
        None,
        "--export",
        help=(
            "Write the listing to this file instead of printing it. The format defaults to "
            "`vethuq settings search export-format` unless --format overrides it."
        ),
    ),
    format_: str | None = typer.Option(
        None, "--format", help="Export format: 'json' or 'html'. Only used with --export."
    ),
    sort: Annotated[
        SourceSort.Order, typer.Option("--sort", help="Sort order: asc or desc.")
    ] = SourceSort.Order.ASC,
    sort_by: Annotated[
        SourceSort.By,
        typer.Option(
            "--sort-by",
            help="Sort by filename, id or status (for the sources list, filename is the path).",
        ),
    ] = SourceSort.By.FILENAME,
) -> None:
    """List registered sources, or the files under one source (id, file, index status)."""
    if target is None:
        if detail:
            error_console.print(
                "--detail needs a source id or path to list the files of.", style=Theme.ERROR
            )
            raise typer.Exit(code=1)
        _list_sources(export, format_, sort, sort_by)
        return

    storage = open_storage()
    try:
        target_export = _resolve_export(storage, export, format_)
        try:
            source = Sources.get(storage, Sources.coerce(target))
            files = SourceSort.files(source, Sources.list_files(storage, source.id), sort, sort_by)
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        max_phase = Deepening.max_phase(storage)
    finally:
        storage.close()

    if target_export is not None:
        output, resolved_format = target_export
        Export.source_files(source, files, output, resolved_format, detail=detail)
        _report_export(len(files), "file(s)", output, resolved_format)
        return

    if not files:
        console.print(SourcePanel.build("No files indexed yet for this source.", "bright_black"))
        return

    if detail:
        for file in files:
            console.print(SourceFiles.detail(source, file, max_phase))
    else:
        console.print(SourceFiles.table(source, files))


def _list_sources(
    export: str | None, format_: str | None, sort: SourceSort.Order, sort_by: SourceSort.By
) -> None:
    storage = open_storage()
    try:
        target_export = _resolve_export(storage, export, format_)
        sources = SourceSort.sources(Sources.list_all(storage), sort, sort_by)
    finally:
        storage.close()

    if target_export is not None:
        output, resolved_format = target_export
        Export.sources(sources, output, resolved_format)
        _report_export(len(sources), "source(s)", output, resolved_format)
        return

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


@app.command("purge")
def purge(
    path_or_id: str = typer.Argument(
        ..., help="Removed source id or path, or the path of a removed file."
    ),
    force: bool = typer.Option(False, "--force", help="Purge without asking for confirmation."),
) -> None:
    """Permanently delete a removed source (or file) and its indexed data now."""
    storage = open_storage()
    try:
        target = Sources.coerce(path_or_id)
        try:
            if not force:
                Sources.check_purgeable(storage, target)
                prompt = Text.assemble(
                    "Permanently delete '", (str(path_or_id), Theme.LABEL), "' and its data?"
                )
                if not Confirm.ask(prompt, console=console, default=False):
                    console.print(SourcePanel.build("Aborted.", "bright_black"))
                    raise typer.Exit(code=0)
            result = Sources.purge(storage, target)
        except (SourceNotFoundError, SourceNotRemovedError) as exc:
            error_console.print(str(exc), style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
    finally:
        storage.close()

    console.print(
        SourcePanel.build(
            Text.assemble((f"Purged {result.kind}: ", Theme.OK), (result.path, "white")),
            Theme.OK,
        )
    )
