"""`vethuq index ...` commands for running OCR indexing on registered sources."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import typer
from rich.prompt import Confirm
from rich.text import Text
from vethuq_core.db import connect
from vethuq_core.index_runner import (
    AlreadyRunningError,
    IndexRunnerError,
    IndexState,
    StaleLockError,
    is_running,
    log_path,
    read_state,
    request_pause,
    request_resume,
    request_stop,
    resolve_targets,
    start_run,
)
from vethuq_core.ocr import get_document_results, pending_file_type_counts
from vethuq_core.settings import THREAD_WORKERS_AUTO
from vethuq_core.sources import SourceNotFoundError, get_source, list_sources

from vethuq_cli.console import console, error_console

app = typer.Typer(help="Run OCR indexing on registered sources.")

_POLL_SECONDS = 1.0
_RUN_STATUS_STYLES = {
    "running": "blue",
    "completed": "green",
    "failed": "red",
    "stopped": "blue",
    "paused": "blue",
}


def _coerce_target(path_or_id: str) -> str | int:
    return int(path_or_id) if path_or_id.isdigit() else path_or_id


def _estimate_eta(conn: sqlite3.Connection, state: IndexState) -> str | None:
    """Estimate time remaining from historical averages in `processing_metrics`.

    Splits the target sources' still-pending files by file_type (pdf/image -
    OCR at very different speeds) and multiplies each type's count by that
    type's average document duration across all past runs, rather than this
    run's own pace, which is noisy - or unavailable - early in a run.
    """
    try:
        sources = resolve_targets(conn, state.target)
    except SourceNotFoundError:
        return None

    remaining_by_type = {"pdf": 0, "image": 0}
    for source in sources:
        counts = pending_file_type_counts(
            conn,
            source,
            only_new_files=source.status != "pending",
            only_failed=state.mode == "restart",
        )
        for file_type, count in counts.items():
            remaining_by_type[file_type] += count

    if not any(remaining_by_type.values()):
        return None

    averages = {
        row["file_type"]: row["avg_duration_seconds"]
        for row in conn.execute(
            "SELECT file_type, avg_duration_seconds FROM processing_metrics "
            "WHERE document_count > 0"
        )
    }
    seconds_left = sum(
        count * averages[file_type]
        for file_type, count in remaining_by_type.items()
        if count > 0 and file_type in averages
    )
    if seconds_left <= 0:
        return None

    minutes, seconds = divmod(int(seconds_left), 60)
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def _print_state(conn: sqlite3.Connection, state: IndexState) -> None:
    percent = (state.processed_files / state.total_files * 100) if state.total_files else 100.0
    status_style = _RUN_STATUS_STYLES.get(state.status, "default")
    console.print(Text.assemble("Status: ", (state.status, f"bold {status_style}")))
    console.print(Text(f"Mode: {state.mode}", style="bright_yellow"))
    console.print(Text(f"Target: {state.target or 'all sources'}", style="bright_yellow"))
    console.print(
        f"Progress: {state.processed_files}/{state.total_files} ({percent:.0f}%), "
        f"{state.failed_files} failed"
    )
    if state.thread_workers_setting == "0":
        workers_label = "disabled (sequential)"
    elif state.thread_workers_setting == THREAD_WORKERS_AUTO:
        thread_word = "thread" if state.workers == 1 else "threads"
        workers_label = f"auto (currently {state.workers} {thread_word})"
    else:
        workers_label = f"{state.workers} threads"
    console.print(f"Workers: {workers_label}")
    if state.current_files:
        names = ", ".join(Path(f).name for f in state.current_files)
        label = "Current files" if len(state.current_files) > 1 else "Current file"
        console.print(f"{label}: {names}")
    if state.status == "running":
        eta = _estimate_eta(conn, state)
        if eta is not None:
            console.print(f"ETA: ~{eta}")


def _start_and_report(target: str | None, *, force: bool, wait: bool, restart: bool) -> None:
    if target is None:
        conn = connect()
        try:
            has_sources = bool(list_sources(conn))
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
        pid = start_run(target, force=force, restart=restart)
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

    while True:
        time.sleep(_POLL_SECONDS)
        state = read_state()
        if state is not None and state.pid == pid:
            if state.status in ("completed", "stopped", "failed"):
                conn = connect()
                try:
                    _print_state(conn, state)
                finally:
                    conn.close()
                return
            continue
        # No state yet for this pid - could just be starting up (the worker
        # hasn't written its first state file yet) or it could genuinely be
        # gone (e.g. crashed before writing anything). Only stop waiting once
        # the process itself is confirmed no longer running.
        running, current_pid = is_running()
        if not running or current_pid != pid:
            console.print(
                "Background run ended before reporting any progress. "
                f"If this is unexpected, check {log_path()} for errors."
            )
            return


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
) -> None:
    """Show background index run progress, or per-file detail for one source."""
    if target is None:
        state = read_state()
        if as_json:
            console.print(state.to_json() if state is not None else "null")
            return
        if state is None:
            console.print("No index run has been started yet.", style="bright_black")
            return
        conn = connect()
        try:
            _print_state(conn, state)
        finally:
            conn.close()
        return

    conn = connect()
    try:
        try:
            source = get_source(conn, _coerce_target(target))
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style="bold red")
            raise typer.Exit(code=1) from exc
        results = get_document_results(conn, source.id)
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
        request_stop()
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
        request_pause()
    except IndexRunnerError as exc:
        error_console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc
    console.print("Index run paused.", style="bold yellow")


@app.command("resume")
def resume() -> None:
    """Resume a paused background index run."""
    try:
        request_resume()
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
    conn = connect()
    try:
        if target is None:
            rows = conn.execute(
                "SELECT * FROM index_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            try:
                get_source(conn, _coerce_target(target))
            except SourceNotFoundError as exc:
                error_console.print(str(exc), style="bold red")
                raise typer.Exit(code=1) from exc
            # A run over "all sources" (target IS NULL) would have covered
            # this source too, so it's included alongside runs targeted at
            # just this source.
            rows = conn.execute(
                "SELECT * FROM index_runs WHERE target = ? OR target IS NULL "
                "ORDER BY started_at DESC LIMIT ?",
                (target, limit),
            ).fetchall()
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
            (row["status"], _RUN_STATUS_STYLES.get(row["status"], "default")),
            f"  {row['processed_files']}/{row['total_files']} processed, "
            f"{row['failed_files']} failed",
            f"  workers={workers if workers is not None else 'n/a'}",
        )
        console.print(line)
