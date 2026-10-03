"""`vethuq index ...` commands for running OCR indexing on registered sources."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.prompt import Confirm
from rich.text import Text
from vethuq_core.index import (
    AlreadyRunningError,
    DatabaseIntegrityError,
    IndexRunner,
    IndexRunnerError,
    StaleLockError,
)
from vethuq_core.ocr import Document
from vethuq_core.sources import SourceNotFoundError, Sources
from vethuq_core.storage import open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.index.panel import IndexPanel, StatePanel
from vethuq_cli.theme import Theme

app = typer.Typer(help="Run OCR indexing on registered sources.")


def _report_recovery(actions: list[str]) -> None:
    """Tell the user what was recovered from a previous run that didn't exit cleanly."""
    text = Text("Recovered from a previous run that didn't exit cleanly:", style="white")
    for action in actions:
        text.append(f"\n  - {action}", style="white")
    console.print(IndexPanel.message(text, Theme.NOTICE))


def _start_and_report(target: str | None, *, force: bool, wait: bool, restart: bool) -> None:
    if target is None:
        storage = open_storage()
        try:
            has_sources = bool(Sources.list_all(storage))
        finally:
            storage.close()
        if not has_sources:
            console.print(
                IndexPanel.message(
                    Text.assemble(
                        ("No sources registered yet. Register one with '", "white"),
                        ("vethuq source add <path>", Theme.COMMAND),
                        ("'.", "white"),
                    ),
                    "bright_black",
                )
            )
            return

    try:
        pid = IndexRunner.start_run(
            target, force=force, restart=restart, on_recovery=_report_recovery
        )
    except (
        AlreadyRunningError,
        StaleLockError,
        DatabaseIntegrityError,
        SourceNotFoundError,
    ) as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc

    verb = "restart" if restart else "index run"
    started = Text.assemble((f"Started background {verb} (pid {pid}).", Theme.OK))
    if not wait:
        started.append("\n\nCheck progress with '", style="white")
        started.append("vethuq index status", style=Theme.COMMAND)
        started.append("'.", style="white")
        console.print(IndexPanel.message(started, Theme.OK))
        return
    console.print(IndexPanel.message(started, Theme.OK))

    storage = open_storage()
    try:
        interrupted = StatePanel.live_wait_or_stop(storage, pid)
    finally:
        storage.close()
    if interrupted:
        raise typer.Exit(code=130)


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
            console.print(
                IndexPanel.message(
                    "No index run has been started yet.", "bright_black", "Index Run"
                )
            )
            return
        storage = open_storage()
        try:
            if wait and state.is_active:
                StatePanel.live_wait(storage, state.pid)
            else:
                StatePanel.print_state(storage, state)
        finally:
            storage.close()
        return

    storage = open_storage()
    try:
        try:
            source = Sources.get(storage, Sources.coerce(target))
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        results = Document.get_results(storage, source.id)
    finally:
        storage.close()

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
        console.print(
            IndexPanel.message(
                "No files indexed yet for this source.", "bright_black", "Index Status"
            )
        )
        return

    table = IndexPanel.new_table()
    table.add_column("File", no_wrap=False, overflow="fold")
    table.add_column("Status")
    table.add_column("Confidence", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Details", no_wrap=False, overflow="fold")
    for r in results:
        name = Path(r.file_path).name
        if r.status == "indexed":
            confidence = f"{r.confidence:.0%}" if r.confidence is not None else "n/a"
            duration = f"{r.duration:.1f}s" if r.duration is not None else "n/a"
            details = (
                f"duplicate of {Path(r.duplicate_of_path).name}"
                if r.duplicate_of_path is not None
                else ""
            )
            table.add_row(name, Text("indexed", style=Theme.OK), confidence, duration, details)
        elif r.status == "error":
            table.add_row(
                name,
                Text("error", style=Theme.ERROR),
                "",
                "",
                Text(str(r.error_message), style=Theme.ERROR),
            )
        else:
            table.add_row(name, Text(r.status, style=Theme.INFO), "", "", "")
    console.print(IndexPanel.table(table, "Index Status"))


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
        console.print(IndexPanel.message("Aborted.", "bright_black"))
        raise typer.Exit(code=0)
    try:
        IndexRunner.request_stop()
    except IndexRunnerError as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc
    console.print(IndexPanel.message("Index run stopped.", Theme.OK))


@app.command("pause")
def pause(
    force: bool = typer.Option(False, "--force", help="Pause without asking for confirmation."),
) -> None:
    """Pause the currently running background index."""
    if not force and not Confirm.ask(
        "Pause the currently running index run?", console=console, default=False
    ):
        console.print(IndexPanel.message("Aborted.", "bright_black"))
        raise typer.Exit(code=0)
    try:
        IndexRunner.request_pause()
    except IndexRunnerError as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc
    console.print(IndexPanel.message("Index run paused.", Theme.WARNING))


@app.command("resume")
def resume() -> None:
    """Resume a paused background index run."""
    try:
        IndexRunner.request_resume()
    except IndexRunnerError as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc
    console.print(IndexPanel.message("Index run resumed.", Theme.OK))


@app.command("history")
def history(
    target: str | None = typer.Argument(
        None, help="Source id or path to filter to (also includes runs over all sources)."
    ),
    limit: int = typer.Option(10, "--limit", help="Number of past runs to show."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List past background index runs, optionally filtered to one source."""
    storage = open_storage()
    try:
        if target is not None:
            try:
                Sources.get(storage, Sources.coerce(target))
            except SourceNotFoundError as exc:
                error_console.print(str(exc), style=Theme.ERROR)
                raise typer.Exit(code=1) from exc
        # A run over "all sources" (target IS NULL) would have covered a
        # specific `target` source too, so it's included alongside runs
        # targeted at just that source.
        runs = IndexRunner.list_runs(storage, target, limit)
    finally:
        storage.close()

    if as_json:
        console.print(json.dumps([run.to_dict() for run in runs]))
        return

    if not runs:
        console.print(
            IndexPanel.message("No index runs recorded yet.", "bright_black", "Index History")
        )
        return

    table = IndexPanel.new_table()
    table.add_column("ID", justify="right", style="bright_black")
    table.add_column("Started", no_wrap=False, overflow="fold")
    table.add_column("Mode", style=Theme.LABEL, no_wrap=True)
    table.add_column("Target", style=Theme.LABEL, no_wrap=False, overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Done", justify="right", no_wrap=True)
    table.add_column("Failed", justify="right", no_wrap=True)
    table.add_column("Workers", justify="right", no_wrap=True)
    for run in runs:
        table.add_row(
            str(run.id),
            IndexPanel.friendly_time(str(run.started_at)),
            run.mode,
            run.target or "all sources",
            Text(run.status, style=StatePanel.RUN_STATUS_STYLES.get(run.status, "default")),
            f"{run.processed_files}/{run.total_files}",
            str(run.failed_files),
            str(run.workers) if run.workers is not None else "n/a",
        )
    console.print(IndexPanel.table(table, "Index History"))
