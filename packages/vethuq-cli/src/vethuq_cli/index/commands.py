"""`vethuq index ...` commands for running OCR indexing on registered sources."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.prompt import Confirm
from rich.text import Text
from vethuq_core.db import Db
from vethuq_core.db.queries import Index
from vethuq_core.index import (
    AlreadyRunningError,
    IndexRunner,
    IndexRunnerError,
    StaleLockError,
)
from vethuq_core.ocr import Document
from vethuq_core.source import SourceNotFoundError, Sources

from vethuq_cli.console import console, error_console
from vethuq_cli.index.panel import StatePanel

app = typer.Typer(help="Run OCR indexing on registered sources.")


def _coerce_target(path_or_id: str) -> str | int:
    return int(path_or_id) if path_or_id.isdigit() else path_or_id


def _start_and_report(target: str | None, *, force: bool, wait: bool, restart: bool) -> None:
    if target is None:
        conn = Db.connect()
        try:
            has_sources = bool(Sources.list_all(conn))
        finally:
            conn.close()
        if not has_sources:
            console.print(
                Text.assemble(
                    "No sources registered yet. Register one with '",
                    ("vethuq source add <path>", "bold cyan"),
                    "'.",
                    style="bright_black",
                )
            )
            return

    try:
        pid = IndexRunner.start_run(target, force=force, restart=restart)
    except (AlreadyRunningError, StaleLockError, SourceNotFoundError) as exc:
        error_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc

    verb = "restart" if restart else "index run"
    console.print(f"Started background {verb} (pid {pid}).", style="bold green")
    if not wait:
        console.print()
        console.print(
            Text.assemble("Check progress with '", ("vethuq index status", "bold cyan"), "'.")
        )
        return

    conn = Db.connect()
    try:
        StatePanel.live_wait(conn, pid)
    finally:
        conn.close()


@app.command("run")
def run(
    target: str | None = typer.Argument(
        None, help="Source id or path to index. Omit to index every pending source."
    ),
    wait: bool = typer.Option(
        False, "--wait", help="Block until the run finishes, printing progress as it goes."
    ),
    force: bool = typer.Option(
        False, "--force", help="Clear a stale lock left by a run that didn't exit cleanly."
    ),
) -> None:
    """Start OCR indexing in the background and return immediately.

    A source that's already fully indexed is still checked for files added
    or modified since the last run - genuinely new files, files whose
    content has changed (by checksum), and previously failed files are
    (re)processed; unchanged files are left untouched. Use 'vethuq index
    status' to check progress.
    """
    _start_and_report(target, force=force, wait=wait, restart=False)


@app.command("restart")
def restart(
    target: str | None = typer.Argument(
        None, help="Source id or path to retry. Omit to retry every source's failed files."
    ),
    wait: bool = typer.Option(
        False, "--wait", help="Block until the run finishes, printing progress as it goes."
    ),
    force: bool = typer.Option(
        False, "--force", help="Clear a stale lock left by a run that didn't exit cleanly."
    ),
) -> None:
    """Retry only previously-failed files, in the background.

    New files and already-indexed files are left untouched - only files
    whose last OCR attempt failed are (re)processed. Use 'vethuq index run'
    instead to also pick up new files.
    """
    _start_and_report(target, force=force, wait=wait, restart=True)


@app.command("status")
def status(
    target: str | None = typer.Argument(
        None, help="Show detailed per-file status for this source id or path."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    wait: bool = typer.Option(
        False, "--wait", help="Live-refresh progress until the run finishes."
    ),
) -> None:
    """Show background index run progress, or per-file detail for one source."""
    if target is None:
        state = IndexRunner.read_state()
        if as_json:
            console.print(state.to_json() if state is not None else "null")
            return
        if state is None:
            console.print("No index run has been started yet.", style="bright_black")
            return
        conn = Db.connect()
        try:
            if wait and state.status in ("running", "paused"):
                StatePanel.live_wait(conn, state.pid)
            else:
                StatePanel.print_state(conn, state)
        finally:
            conn.close()
        return

    conn = Db.connect()
    try:
        try:
            source = Sources.get(conn, _coerce_target(target))
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style="bold red")
            raise typer.Exit(code=1) from exc
        results = Document.get_results(conn, source.id)
    finally:
        conn.close()

    if as_json:
        console.print(
            json.dumps(
                [
                    {
                        "file": r.file_path,
                        "status": r.status,
                        "confidence": r.confidence,
                        "duration": r.duration,
                        "error": r.error_message,
                        "duplicate_of": r.duplicate_of_path,
                    }
                    for r in results
                ]
            )
        )
        return

    if not results:
        console.print("No files indexed yet for this source.", style="bright_black")
        return

    for r in results:
        name = Path(r.file_path).name
        line = Text(f"  {name:<40} ")
        if r.status == "indexed":
            confidence = f"{r.confidence:.0%}" if r.confidence is not None else "n/a"
            duration = f"{r.duration:.1f}s" if r.duration is not None else "n/a"
            line.append("indexed ", style="bold green")
            line.append(f" confidence: {confidence}  duration: {duration}")
            if r.duplicate_of_path is not None:
                line.append(f"  (duplicate of {Path(r.duplicate_of_path).name})")
        elif r.status == "error":
            line.append("error   ", style="bold red")
            line.append(f" {r.error_message}")
        else:
            line.append(r.status, style="bold blue")
        console.print(line)


@app.command("stop")
def stop(
    force: bool = typer.Option(False, "--force", help="Stop without asking for confirmation."),
) -> None:
    """Force-stop the currently running background index."""
    if not force and not Confirm.ask(
        "Stop the currently running index run? Progress on the current file will be lost.",
        console=console,
        default=False,
    ):
        console.print("Aborted.", style="bright_black")
        raise typer.Exit(code=0)
    try:
        IndexRunner.request_stop()
    except IndexRunnerError as exc:
        error_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc
    console.print("Index run stopped.", style="bold green")


@app.command("pause")
def pause(
    force: bool = typer.Option(False, "--force", help="Pause without asking for confirmation."),
) -> None:
    """Pause the currently running background index."""
    if not force and not Confirm.ask(
        "Pause the currently running index run?", console=console, default=False
    ):
        console.print("Aborted.", style="bright_black")
        raise typer.Exit(code=0)
    try:
        IndexRunner.request_pause()
    except IndexRunnerError as exc:
        error_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc
    console.print("Index run paused.", style="bold yellow")


@app.command("resume")
def resume() -> None:
    """Resume a paused background index run."""
    try:
        IndexRunner.request_resume()
    except IndexRunnerError as exc:
        error_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc
    console.print("Index run resumed.", style="bold green")


@app.command("history")
def history(
    target: str | None = typer.Argument(
        None, help="Source id or path to filter to (also includes runs over all sources)."
    ),
    limit: int = typer.Option(10, "--limit", help="Number of past runs to show."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List past background index runs, optionally filtered to one source."""
    conn = Db.connect()
    try:
        if target is not None:
            try:
                Sources.get(conn, _coerce_target(target))
            except SourceNotFoundError as exc:
                error_console.print(str(exc), style="bold red")
                raise typer.Exit(code=1) from exc
        # A run over "all sources" (target IS NULL) would have covered a
        # specific `target` source too, so it's included alongside runs
        # targeted at just that source.
        rows = Index.list_runs(conn, target, limit)
    finally:
        conn.close()

    if as_json:
        console.print(json.dumps([dict(row) for row in rows]))
        return

    if not rows:
        console.print("No index runs recorded yet.", style="bright_black")
        return

    for row in rows:
        target = row["target"] or "all sources"
        workers = row["workers"]
        line = Text.assemble(
            "[",
            (str(row["id"]), "bright_black"),
            f"] {row['started_at']}  ",
            (f"mode={row['mode']}", "bright_yellow"),
            "  ",
            (f"target={target}", "bright_yellow"),
            "  status=",
            (row["status"], StatePanel.RUN_STATUS_STYLES.get(row["status"], "default")),
            f"  {row['processed_files']}/{row['total_files']} processed, "
            f"{row['failed_files']} failed",
            f"  workers={workers if workers is not None else 'n/a'}",
        )
        console.print(line)
