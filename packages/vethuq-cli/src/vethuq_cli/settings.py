"""`vethuq settings ...` commands for configuring VethuQ."""

from __future__ import annotations

import typer
from rich.text import Text
from vethuq_core.db import connect
from vethuq_core.settings import (
    SEARCH_EXPORT_FORMATS,
    STALE_LOCK_VALUES,
    THREAD_WORKERS_AUTO,
    THREAD_WORKERS_MAX,
    get_ocr_retry_attempts,
    get_removed_source_retention_minutes,
    get_search_export_format,
    get_search_snippet_context_chars,
    get_stale_lock,
    get_thread_workers,
    is_gpu_enabled,
    set_gpu_enabled,
    set_ocr_retry_attempts,
    set_removed_source_retention_minutes,
    set_search_export_format,
    set_search_snippet_context_chars,
    set_stale_lock,
    set_thread_workers,
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
app.add_typer(gpu_app, name="gpu")
app.add_typer(search_app, name="search")
search_app.add_typer(snippet_app, name="snippet")
search_app.add_typer(export_format_app, name="export-format")
app.add_typer(index_app, name="index")
index_app.add_typer(removed_retention_app, name="removed-retention")
index_app.add_typer(ocr_retry_app, name="ocr-retry")
index_app.add_typer(thread_workers_app, name="thread-workers")
index_app.add_typer(stale_lock_app, name="stale-lock")


@gpu_app.command("enable")
def gpu_enable() -> None:
    """Enable GPU use for OCR.

    Only takes effect if a CUDA-capable PaddlePaddle build with a visible GPU
    is actually installed - otherwise OCR silently falls back to CPU.
    """
    conn = connect()
    try:
        set_gpu_enabled(conn, True)
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
    conn = connect()
    try:
        set_gpu_enabled(conn, False)
        console.print("GPU disabled. OCR will run on CPU.", style="bright_black")
    finally:
        conn.close()


@gpu_app.command("status")
def gpu_status() -> None:
    """Show whether GPU use is currently enabled."""
    conn = connect()
    try:
        enabled = is_gpu_enabled(conn)
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
    conn = connect()
    try:
        console.print(
            Text.assemble(
                "Search snippet context: ",
                (str(get_search_snippet_context_chars(conn)), "bright_blue"),
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
    conn = connect()
    try:
        try:
            set_search_snippet_context_chars(conn, chars)
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
    conn = connect()
    try:
        console.print(
            Text.assemble("Search export format: ", (get_search_export_format(conn), "bright_blue"))
        )
    finally:
        conn.close()


@export_format_app.command("set")
def export_format_set(
    format_: str = typer.Argument(
        ..., metavar="FORMAT", help=f"One of: {', '.join(SEARCH_EXPORT_FORMATS)}."
    ),
) -> None:
    """Set the default format `search --export` writes to when none is given."""
    conn = connect()
    try:
        try:
            set_search_export_format(conn, format_)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Search export format set to ", (format_, "bright_blue"), "."))
    finally:
        conn.close()


@removed_retention_app.command("show")
def removed_retention_show() -> None:
    """Show, in minutes, how long a removed source is kept before it's purged from the DB."""
    conn = connect()
    try:
        console.print(
            Text.assemble(
                "Removed source retention: ",
                (str(get_removed_source_retention_minutes(conn)), "bright_blue"),
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
    conn = connect()
    try:
        try:
            set_removed_source_retention_minutes(conn, minutes)
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
    conn = connect()
    try:
        console.print(
            Text.assemble(
                "OCR retry attempts: ", (str(get_ocr_retry_attempts(conn)), "bright_blue")
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
    conn = connect()
    try:
        try:
            set_ocr_retry_attempts(conn, attempts)
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
    conn = connect()
    try:
        value = get_thread_workers(conn)
        label = "disabled (sequential)" if value == "0" else value
        console.print(Text.assemble("Thread workers: ", (label, "bright_blue")))
    finally:
        conn.close()


@thread_workers_app.command("set")
def thread_workers_set(
    value: str = typer.Argument(
        ...,
        metavar="VALUE",
        help=f"0 (disable), 1-{THREAD_WORKERS_MAX}, or '{THREAD_WORKERS_AUTO}'.",
    ),
) -> None:
    """Set how many worker threads background indexing uses."""
    conn = connect()
    try:
        try:
            set_thread_workers(conn, value)
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
    conn = connect()
    try:
        console.print(Text.assemble("Stale lock: ", (get_stale_lock(conn), "bright_blue")))
    finally:
        conn.close()


@stale_lock_app.command("set")
def stale_lock_set(
    value: str = typer.Argument(
        ..., metavar="VALUE", help=f"One of: {', '.join(STALE_LOCK_VALUES)}."
    ),
) -> None:
    """Set whether a stale lock is auto-cleared on the next run."""
    conn = connect()
    try:
        try:
            set_stale_lock(conn, value)
        except ValueError as exc:
            error_console.print(f"Error: {exc}", style="bold red")
            raise typer.Exit(code=1) from exc
        console.print(Text.assemble("Stale lock set to ", (value, "bright_blue"), "."))
    finally:
        conn.close()
