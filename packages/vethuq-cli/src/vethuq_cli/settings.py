"""`vethuq settings ...` commands for configuring VethuQ."""

from __future__ import annotations

import typer
from rich.text import Text
from vethuq_core.db import Db
from vethuq_core.settings import (
    GpuSettings,
    IndexSettings,
    OcrSettings,
    SearchSettings,
    SourceSettings,
)

from vethuq_cli.console import console, error_console

app = typer.Typer(help="Manage VethuQ settings.")
gpu_app = typer.Typer(help="Configure whether OCR should use the GPU when available.")
search_app = typer.Typer(help="Configure `search` behavior.")
snippet_app = typer.Typer(help="Configure how much context `search` shows around a match.")
export_format_app = typer.Typer(help="Configure the default format `search --export` writes to.")
index_app = typer.Typer(help="Configure indexing behavior.")
removed_retention_app = typer.Typer(
    help="Configure, in minutes, how long a removed source is kept before it's purged from the DB."
)
ocr_retry_app = typer.Typer(
    help="Configure how many times to retry a file's OCR after a transient failure."
)
thread_workers_app = typer.Typer(help="Configure how many worker threads background indexing uses.")
stale_lock_app = typer.Typer(
    help="Configure whether a lock left behind by a run that didn't exit cleanly "
    "is auto-cleared on the next run."
)
engine_app = typer.Typer(
    help="Configure how thoroughly OCR looks for rotated text: quick, moderate or deep."
)
app.add_typer(gpu_app, name="gpu")
app.add_typer(search_app, name="search")
search_app.add_typer(snippet_app, name="snippet")
search_app.add_typer(export_format_app, name="export-format")
app.add_typer(index_app, name="index")
index_app.add_typer(removed_retention_app, name="removed-retention")
index_app.add_typer(ocr_retry_app, name="ocr-retry")
index_app.add_typer(thread_workers_app, name="thread-workers")
index_app.add_typer(stale_lock_app, name="stale-lock")
index_app.add_typer(engine_app, name="engine")


@gpu_app.command("enable")
def gpu_enable() -> None:
    """Enable GPU use for OCR.

    Only takes effect if a CUDA-capable PaddlePaddle build with a visible GPU
    is actually installed - otherwise OCR silently falls back to CPU.
    """
    conn = Db.connect()
    try:
        GpuSettings.set_enabled(conn, True)
        console.print(
            "GPU enabled. It will be used next time OCR runs, if a CUDA-capable "
            "PaddleOCR build is installed; otherwise CPU is used.",
            style="bold green",
        )
    finally:
        conn.close()


@gpu_app.command("disable")
def gpu_disable() -> None:
    """Disable GPU use for OCR (the default) - OCR always runs on CPU."""
    conn = Db.connect()
    try:
        GpuSettings.set_enabled(conn, False)
        console.print("GPU disabled. OCR will run on CPU.", style="bright_black")
    finally:
        conn.close()


@gpu_app.command("status")
def gpu_status() -> None:
    """Show whether GPU use is currently enabled."""
    conn = Db.connect()
    try:
        enabled = GpuSettings.is_enabled(conn)
        line = Text("GPU: ")
        line.append(
            "enabled" if enabled else "disabled", style="green" if enabled else "bright_black"
        )
        console.print(line)
    finally:
        conn.close()


@snippet_app.command("show")
def snippet_show() -> None:
    """Show how many characters of context `search` shows around a match."""
    conn = Db.connect()
    try:
        console.print(
            Text.assemble(
                "Search snippet context: ",
                (str(SearchSettings.get_snippet_context_chars(conn)), "bright_blue"),
                " characters",
            )
        )
    finally:
        conn.close()


@snippet_app.command("set")
def snippet_set(
    chars: int = typer.Argument(..., help="Characters of context to show on each side of a match."),
) -> None:
    """Set how many characters of context `search` shows around a match."""
    conn = Db.connect()
    try:
        try:
            SearchSettings.set_snippet_context_chars(conn, chars)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble(
                "Search snippet context set to ", (str(chars), "bright_blue"), " characters."
            )
        )
    finally:
        conn.close()


@export_format_app.command("show")
def export_format_show() -> None:
    """Show the default format `search --export` writes to when none is given."""
    conn = Db.connect()
    try:
        console.print(
            Text.assemble(
                "Search export format: ", (SearchSettings.get_export_format(conn), "bright_blue")
            )
        )
    finally:
        conn.close()


@export_format_app.command("set")
def export_format_set(
    format_: str = typer.Argument(
        ..., metavar="FORMAT", help=f"One of: {', '.join(SearchSettings.EXPORT_FORMATS)}."
    ),
) -> None:
    """Set the default format `search --export` writes to when none is given."""
    conn = Db.connect()
    try:
        try:
            SearchSettings.set_export_format(conn, format_)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Search export format set to ", (format_, "bright_blue"), "."))
    finally:
        conn.close()


@removed_retention_app.command("show")
def removed_retention_show() -> None:
    """Show, in minutes, how long a removed source is kept before it's purged from the DB."""
    conn = Db.connect()
    try:
        console.print(
            Text.assemble(
                "Removed source retention: ",
                (str(SourceSettings.get_removed_retention_minutes(conn)), "bright_blue"),
                " minutes",
            )
        )
    finally:
        conn.close()


@removed_retention_app.command("set")
def removed_retention_set(
    minutes: int = typer.Argument(
        ..., help="Minutes to keep a removed source before it's purged from the DB."
    ),
) -> None:
    """Set, in minutes, how long a removed source is kept before it's purged from the DB."""
    conn = Db.connect()
    try:
        try:
            SourceSettings.set_removed_retention_minutes(conn, minutes)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble(
                "Removed source retention set to ", (str(minutes), "bright_blue"), " minutes."
            )
        )
    finally:
        conn.close()


@ocr_retry_app.command("show")
def ocr_retry_show() -> None:
    """Show how many times a file's OCR is retried after a transient failure."""
    conn = Db.connect()
    try:
        console.print(
            Text.assemble(
                "OCR retry attempts: ", (str(OcrSettings.get_retry_attempts(conn)), "bright_blue")
            )
        )
    finally:
        conn.close()


@ocr_retry_app.command("set")
def ocr_retry_set(
    attempts: int = typer.Argument(
        ..., help="Times to retry a file's OCR after a transient failure."
    ),
) -> None:
    """Set how many times a file's OCR is retried after a transient failure."""
    conn = Db.connect()
    try:
        try:
            OcrSettings.set_retry_attempts(conn, attempts)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(
            Text.assemble("OCR retry attempts set to ", (str(attempts), "bright_blue"), ".")
        )
    finally:
        conn.close()


@thread_workers_app.command("show")
def thread_workers_show() -> None:
    """Show how many worker threads background indexing uses."""
    conn = Db.connect()
    try:
        value = IndexSettings.get_thread_workers(conn)
        label = "disabled (sequential)" if value == "0" else value
        console.print(Text.assemble("Thread workers: ", (label, "bright_blue")))
    finally:
        conn.close()


@thread_workers_app.command("set")
def thread_workers_set(
    value: str = typer.Argument(
        ...,
        metavar="VALUE",
        help=(
            f"0 (disable), 1-{IndexSettings.THREAD_WORKERS_MAX}, "
            f"or '{IndexSettings.THREAD_WORKERS_AUTO}'."
        ),
    ),
) -> None:
    """Set how many worker threads background indexing uses."""
    conn = Db.connect()
    try:
        try:
            IndexSettings.set_thread_workers(conn, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        label = "disabled (sequential)" if value == "0" else value
        console.print(Text.assemble("Thread workers set to ", (label, "bright_blue"), "."))
    finally:
        conn.close()


@stale_lock_app.command("show")
def stale_lock_show() -> None:
    """Show whether a stale lock is auto-cleared on the next run."""
    conn = Db.connect()
    try:
        console.print(
            Text.assemble("Stale lock: ", (IndexSettings.get_stale_lock(conn), "bright_blue"))
        )
    finally:
        conn.close()


@stale_lock_app.command("set")
def stale_lock_set(
    value: str = typer.Argument(
        ..., metavar="VALUE", help=f"One of: {', '.join(IndexSettings.STALE_LOCK_VALUES)}."
    ),
) -> None:
    """Set whether a stale lock is auto-cleared on the next run."""
    conn = Db.connect()
    try:
        try:
            IndexSettings.set_stale_lock(conn, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Stale lock set to ", (value, "bright_blue"), "."))
    finally:
        conn.close()


@engine_app.command("show")
def engine_show() -> None:
    """Show how thoroughly OCR looks for rotated text."""
    conn = Db.connect()
    try:
        console.print(Text.assemble("OCR engine: ", (OcrSettings.get_engine(conn), "bright_blue")))
    finally:
        conn.close()


@engine_app.command("set")
def engine_set(
    value: str = typer.Argument(
        ...,
        metavar="VALUE",
        help=(
            f"One of: {', '.join(OcrSettings.ENGINE_MODES)}. quick reads upright text only; "
            "moderate "
            "also reads 90/180/270 degree rotations; deep also reads every 15 degrees. "
            "Files are always indexed quick first, then deeper passes run in the background."
        ),
    ),
) -> None:
    """Set how thoroughly OCR looks for rotated text.

    Every file is indexed quick first so it's searchable right away; moderate
    and deep then add text found in rotated passes while indexing continues.
    Files already indexed are brought up to the new level the next time
    indexing runs.
    """
    conn = Db.connect()
    try:
        try:
            OcrSettings.set_engine(conn, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("OCR engine set to ", (value, "bright_blue"), "."))
    finally:
        conn.close()
