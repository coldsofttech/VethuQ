"""`vethuq index ...` commands for running OCR indexing on registered sources."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from vethuq_core.db import connect
from vethuq_core.index_runner import (
    AlreadyRunningError,
    IndexRunnerError,
    IndexState,
    StaleLockError,
    is_running,
    read_state,
    request_pause,
    request_resume,
    request_stop,
    start_run,
)
from vethuq_core.ocr import get_document_results
from vethuq_core.sources import SourceNotFoundError, get_source

app = typer.Typer(help="Run OCR indexing on registered sources.")

_POLL_SECONDS = 1.0


def _coerce_target(path_or_id: str) -> str | int:
    return int(path_or_id) if path_or_id.isdigit() else path_or_id


def _estimate_eta(state: IndexState) -> str | None:
    if state.processed_files == 0 or state.total_files == 0:
        return None
    elapsed = (datetime.now(UTC) - datetime.fromisoformat(state.started_at)).total_seconds()
    remaining = state.total_files - state.processed_files
    if elapsed <= 0 or remaining <= 0:
        return None
    seconds_left = remaining / (state.processed_files / elapsed)
    minutes, seconds = divmod(int(seconds_left), 60)
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def _print_state(state: IndexState) -> None:
    percent = (state.processed_files / state.total_files * 100) if state.total_files else 100.0
    typer.echo(f"Status: {state.status}")
    typer.echo(f"Mode: {state.mode}")
    typer.echo(f"Target: {state.target or 'all sources'}")
    typer.echo(
        f"Progress: {state.processed_files}/{state.total_files} ({percent:.0f}%), "
        f"{state.failed_files} failed"
    )
    if state.current_file:
        typer.echo(f"Current file: {Path(state.current_file).name}")
    if state.status == "running":
        eta = _estimate_eta(state)
        if eta is not None:
            typer.echo(f"ETA: ~{eta}")


def _start_and_report(target: str | None, *, force: bool, wait: bool, restart: bool) -> None:
    try:
        pid = start_run(target, force=force, restart=restart)
    except (AlreadyRunningError, StaleLockError, SourceNotFoundError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    verb = "restart" if restart else "index run"
    typer.echo(f"Started background {verb} (pid {pid}).")
    if not wait:
        typer.echo("Check progress with 'vethuq index status'.")
        return

    while True:
        time.sleep(_POLL_SECONDS)
        state = read_state()
        if state is not None and state.pid == pid:
            if state.status in ("completed", "stopped", "failed"):
                _print_state(state)
                return
            continue
        # No state yet for this pid - could just be starting up (the worker
        # hasn't written its first state file yet) or it could genuinely be
        # gone (e.g. crashed before writing anything). Only stop waiting once
        # the process itself is confirmed no longer running.
        running, current_pid = is_running()
        if not running or current_pid != pid:
            typer.echo("Background run ended before reporting any progress.")
            return


@app.command("run")
def run(
    target: str = typer.Argument(
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
    to it since the last run - only genuinely new (or previously failed)
    files are (re)processed. Use 'vethuq index status' to check progress.
    """
    _start_and_report(target, force=force, wait=wait, restart=False)


@app.command("restart")
def restart(
    target: str = typer.Argument(
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
    target: str = typer.Argument(
        None, help="Show detailed per-file status for this source id or path."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show background index run progress, or per-file detail for one source."""
    if target is None:
        state = read_state()
        if as_json:
            typer.echo(state.to_json() if state is not None else "null")
            return
        if state is None:
            typer.echo("No index run has been started yet.")
            return
        _print_state(state)
        return

    conn = connect()
    try:
        try:
            source = get_source(conn, _coerce_target(target))
        except SourceNotFoundError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        results = get_document_results(conn, source.id)
    finally:
        conn.close()

    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "file": r.file_path,
                        "status": r.status,
                        "confidence": r.confidence,
                        "duration": r.duration,
                        "error": r.error_message,
                    }
                    for r in results
                ]
            )
        )
        return

    if not results:
        typer.echo("No files indexed yet for this source.")
        return

    for r in results:
        name = Path(r.file_path).name
        if r.status == "indexed":
            confidence = f"{r.confidence:.0%}" if r.confidence is not None else "n/a"
            duration = f"{r.duration:.1f}s" if r.duration is not None else "n/a"
            typer.echo(f"  {name:<40} indexed  confidence: {confidence}  duration: {duration}")
        elif r.status == "error":
            typer.echo(f"  {name:<40} error    {r.error_message}")
        else:
            typer.echo(f"  {name:<40} {r.status}")


@app.command("stop")
def stop() -> None:
    """Force-stop the currently running background index."""
    try:
        request_stop()
    except IndexRunnerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Index run stopped.")


@app.command("pause")
def pause() -> None:
    """Pause the currently running background index."""
    try:
        request_pause()
    except IndexRunnerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Index run paused.")


@app.command("resume")
def resume() -> None:
    """Resume a paused background index run."""
    try:
        request_resume()
    except IndexRunnerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Index run resumed.")


@app.command("history")
def history(
    limit: int = typer.Option(10, "--limit", help="Number of past runs to show."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List past background index runs."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM index_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()

    if as_json:
        typer.echo(json.dumps([dict(row) for row in rows]))
        return

    if not rows:
        typer.echo("No index runs recorded yet.")
        return

    for row in rows:
        target = row["target"] or "all sources"
        typer.echo(
            f"[{row['id']}] {row['started_at']}  mode={row['mode']}  target={target}  "
            f"status={row['status']}  {row['processed_files']}/{row['total_files']} processed, "
            f"{row['failed_files']} failed"
        )
