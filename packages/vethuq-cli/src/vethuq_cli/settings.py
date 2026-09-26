"""`vethuq settings ...` commands for configuring VethuQ."""

from __future__ import annotations

import typer
from vethuq_core.db import connect
from vethuq_core.settings import (
    get_removed_source_retention_minutes,
    get_search_snippet_context_chars,
    is_gpu_enabled,
    set_gpu_enabled,
    set_removed_source_retention_minutes,
    set_search_snippet_context_chars,
)

app = typer.Typer(help="Manage VethuQ settings.")
gpu_app = typer.Typer(help="Configure whether OCR should use the GPU when available.")
search_app = typer.Typer(help="Configure `search` behavior.")
snippet_app = typer.Typer(help="Configure how much context `search` shows around a match.")
index_app = typer.Typer(help="Configure indexing behavior.")
removed_retention_app = typer.Typer(
    help="Configure, in minutes, how long a removed source is kept before it's purged from the DB."
)
app.add_typer(gpu_app, name="gpu")
app.add_typer(search_app, name="search")
search_app.add_typer(snippet_app, name="snippet")
app.add_typer(index_app, name="index")
index_app.add_typer(removed_retention_app, name="removed-retention")


@gpu_app.command("enable")
def gpu_enable() -> None:
    """Enable GPU use for OCR.

    Only takes effect if a CUDA-capable PaddlePaddle build with a visible GPU
    is actually installed - otherwise OCR silently falls back to CPU.
    """
    conn = connect()
    try:
        set_gpu_enabled(conn, True)
        typer.echo(
            "GPU enabled. It will be used next time OCR runs, if a CUDA-capable "
            "PaddleOCR build is installed; otherwise CPU is used."
        )
    finally:
        conn.close()


@gpu_app.command("disable")
def gpu_disable() -> None:
    """Disable GPU use for OCR (the default) - OCR always runs on CPU."""
    conn = connect()
    try:
        set_gpu_enabled(conn, False)
        typer.echo("GPU disabled. OCR will run on CPU.")
    finally:
        conn.close()


@gpu_app.command("status")
def gpu_status() -> None:
    """Show whether GPU use is currently enabled."""
    conn = connect()
    try:
        typer.echo(f"GPU: {'enabled' if is_gpu_enabled(conn) else 'disabled'}")
    finally:
        conn.close()


@snippet_app.command("show")
def snippet_show() -> None:
    """Show how many characters of context `search` shows around a match."""
    conn = connect()
    try:
        typer.echo(f"Search snippet context: {get_search_snippet_context_chars(conn)} characters")
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
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"Search snippet context set to {chars} characters.")
    finally:
        conn.close()


@removed_retention_app.command("show")
def removed_retention_show() -> None:
    """Show, in minutes, how long a removed source is kept before it's purged from the DB."""
    conn = connect()
    try:
        typer.echo(
            f"Removed source retention: {get_removed_source_retention_minutes(conn)} minutes"
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
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"Removed source retention set to {minutes} minutes.")
    finally:
        conn.close()
