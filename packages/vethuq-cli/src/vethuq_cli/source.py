"""`vethuq source ...` commands for registering files and folders as sources."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.ocr import Deepening
from vethuq_core.sources import (
    Source,
    SourceAlreadyExistsError,
    SourceFile,
    SourceNotFoundError,
    SourcePathError,
    Sources,
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
    def _timestamp(value: str | None) -> str:
        if not value:
            return "-"
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _size(size: int | None) -> str:
        if size is None:
            return "-"
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    @staticmethod
    def _seconds(seconds: float | None) -> str:
        return "-" if seconds is None else f"{seconds:.1f}s"

    @staticmethod
    def _name(source: Source, file: SourceFile) -> str:
        """The file's path relative to a folder source (its name, for a file source)."""
        if source.source_type == "folder":
            try:
                return Path(file.file_path).relative_to(source.path).as_posix()
            except ValueError:
                pass
        return Path(file.file_path).name

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
            table.add_row(str(file.id), SourceFiles._name(source, file), SourceFiles._status(file))
        return SourcePanel.build(table, Theme.PRIMARY, title=f"Sources / {source.path}")

    @staticmethod
    def detail(source: Source, file: SourceFile, max_phase: int) -> Panel:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style=Theme.LABEL, no_wrap=True)
        grid.add_column(no_wrap=False, overflow="fold")

        grid.add_row("Status", SourceFiles._status(file))
        grid.add_row("Type", file.file_type)
        grid.add_row("Size", SourceFiles._size(file.file_size_bytes))
        grid.add_row("Pages", str(file.pages) if file.pages else "-")
        grid.add_row("Started", SourceFiles._timestamp(file.started_at))
        grid.add_row("Completed", SourceFiles._timestamp(file.completed_at))
        grid.add_row("Indexed", SourceFiles._timestamp(file.indexed_at))
        grid.add_row("Duration", SourceFiles._seconds(file.duration))
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
                f"started {SourceFiles._timestamp(timing.started_at)}, "
                f"completed {SourceFiles._timestamp(timing.completed_at)}, "
                f"took {SourceFiles._seconds(timing.duration_seconds)}",
            )
        if file.retry_count:
            grid.add_row("Retries", str(file.retry_count))
        if file.duplicate_of_path:
            grid.add_row("Duplicate of", file.duplicate_of_path)
        if file.error_message:
            grid.add_row("Error", Text(file.error_message, style=Theme.ERROR))

        title = f"Sources / [{file.id}] {SourceFiles._name(source, file)}"
        return SourcePanel.build(grid, Theme.PRIMARY, title=title)


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
) -> None:
    """List registered sources, or the files under one source (id, file, index status)."""
    if target is None:
        if detail:
            error_console.print(
                "--detail needs a source id or path to list the files of.", style=Theme.ERROR
            )
            raise typer.Exit(code=1)
        _list_sources()
        return

    storage = open_storage()
    try:
        try:
            source = Sources.get(storage, Sources.coerce(target))
            files = Sources.list_files(storage, source.id)
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        max_phase = Deepening.max_phase(storage)
    finally:
        storage.close()

    if not files:
        console.print(SourcePanel.build("No files indexed yet for this source.", "bright_black"))
        return

    if detail:
        for file in files:
            console.print(SourceFiles.detail(source, file, max_phase))
    else:
        console.print(SourceFiles.table(source, files))


def _list_sources() -> None:
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
