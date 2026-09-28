"""`vethuq index ...` commands for running OCR indexing on registered sources."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import typer
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn
from rich.progress import TextColumn as ProgressTextColumn
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.db import (
    connect,
    get_processing_metrics_avg_duration_by_file_type,
    list_index_runs,
)
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
from vethuq_core.ocr import get_document_results, new_file_type_counts, pending_file_type_counts
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

    remaining_by_type = new_file_type_counts()
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

    # processing_metrics has one row per (file_type, size_bucket) - weight each
    # bucket's average by its document_count so a file_type with an uneven mix
    # of small/large files still gets one sensible average duration back.
    averages = {
        row["file_type"]: row["avg_duration_seconds"]
        for row in get_processing_metrics_avg_duration_by_file_type(conn)
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


def _progress_bar(processed: int, total: int) -> Progress:
    """A `Progress` renderable showing an animated bar plus count and percentage.

    Not started (`.start()` is never called) - it's rendered as a plain,
    self-contained renderable, either once for a static snapshot or repeatedly
    via `Live.update()`, without spinning up its own refresh thread.
    """
    bar = Progress(
        BarColumn(bar_width=30),
        ProgressTextColumn("{task.completed}/{task.total}"),
        TaskProgressColumn(),
    )
    bar.add_task("progress", total=total or 1, completed=processed)
    return bar


def _build_state_panel(conn: sqlite3.Connection, state: IndexState, *, animated: bool) -> Panel:
    status_style = _RUN_STATUS_STYLES.get(state.status, "default")

    table = Table.grid(padding=(0, 1))
    table.add_column(style="bright_yellow", no_wrap=True)
    table.add_column()

    table.add_row("Status", Text(state.status, style=f"bold {status_style}"))
    table.add_row("Mode", state.mode)
    table.add_row("Target", state.target or "all sources")

    if animated:
        table.add_row("Progress", _progress_bar(state.processed_files, state.total_files))
    else:
        percent = (state.processed_files / state.total_files * 100) if state.total_files else 100.0
        table.add_row("Progress", f"{state.processed_files}/{state.total_files} ({percent:.0f}%)")
    failed_style = "bold red" if state.failed_files else "default"
    table.add_row("Failed", Text(str(state.failed_files), style=failed_style))

    if state.thread_workers_setting == "0":
        workers_label = "disabled (sequential)"
    elif state.thread_workers_setting == THREAD_WORKERS_AUTO:
        thread_word = "thread" if state.workers == 1 else "threads"
        workers_label = f"auto (currently {state.workers} {thread_word})"
    else:
        workers_label = f"{state.workers} threads"
    table.add_row("Workers", workers_label)

    if state.current_files:
        label = "Current files" if len(state.current_files) > 1 else "Current file"
        files_text = Text("\n".join(f"• {Path(f).name}" for f in state.current_files))
        table.add_row(label, files_text)

    if state.status == "running":
        eta = _estimate_eta(conn, state)
        if eta is not None:
            table.add_row("ETA", f"~{eta}")

    border_style = status_style if status_style != "default" else "white"
    return Panel(table, title="Index Run", border_style=border_style, expand=False)


def _print_state(conn: sqlite3.Connection, state: IndexState) -> None:
    console.print(_build_state_panel(conn, state, animated=False))


def _live_wait(conn: sqlite3.Connection, pid: int) -> None:
    """Live-refresh the state panel until the run owned by `pid` reaches a terminal state."""
    with Live(console=console, refresh_per_second=4) as live:
        while True:
            time.sleep(_POLL_SECONDS)
            state = read_state()
            if state is not None and state.pid == pid:
                live.update(_build_state_panel(conn, state, animated=True))
                if state.status in ("completed", "stopped", "failed"):
                    return
                continue
            # No state yet for this pid - could just be starting up (the worker
            # hasn't written its first state file yet) or it could genuinely be
            # gone (e.g. crashed before writing anything). Only stop waiting once
            # the process itself is confirmed no longer running.
            running, current_pid = is_running()
            if not running or current_pid != pid:
                live.stop()
                console.print(
                    "Background run ended before reporting any progress. "
                    f"If this is unexpected, check {log_path()} for errors."
                )
                return


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

    conn = connect()
    try:
        _live_wait(conn, pid)
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
        state = read_state()
        if as_json:
            console.print(state.to_json() if state is not None else "null")
            return
        if state is None:
            console.print("No index run has been started yet.", style="bright_black")
            return
        conn = connect()
        try:
            if wait and state.status in ("running", "paused"):
                _live_wait(conn, state.pid)
            else:
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
        if target is not None:
            try:
                get_source(conn, _coerce_target(target))
            except SourceNotFoundError as exc:
                error_console.print(str(exc), style="bold red")
                raise typer.Exit(code=1) from exc
        # A run over "all sources" (target IS NULL) would have covered a
        # specific `target` source too, so it's included alongside runs
        # targeted at just that source.
        rows = list_index_runs(conn, target, limit)
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
