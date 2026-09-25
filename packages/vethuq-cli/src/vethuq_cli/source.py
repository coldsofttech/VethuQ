"""`vethuq source ...` commands for registering files and folders as sources."""

from __future__ import annotations

import typer
from vethuq_core.db import connect
from vethuq_core.sources import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    SourcePathError,
    add_source,
    list_sources,
    remove_source,
)

app = typer.Typer(help="Manage files and folders registered as VethuQ sources.")


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
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    else:
        typer.echo(f"Added {source.source_type}: {source.path}")
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
        typer.echo("No sources registered yet.")
        return

    for source in sources:
        typer.echo(f"[{source.id}] {source.source_type:<6} {source.status:<8} {source.path}")


@app.command("remove")
def remove(
    path_or_id: str = typer.Argument(..., help="Registered source id or path to remove."),
) -> None:
    """Remove a registered source."""
    conn = connect()
    try:
        target: str | int = int(path_or_id) if path_or_id.isdigit() else path_or_id
        source = remove_source(conn, target)
    except SourceNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    else:
        typer.echo(f"Removed {source.source_type}: {source.path}")
    finally:
        conn.close()
