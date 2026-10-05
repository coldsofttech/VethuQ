"""`vethuq index ...` commands for running OCR indexing on registered sources."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import typer
from rich.prompt import Confirm, Prompt
from rich.text import Text
from typer._click.core import Context
from typer.core import TyperGroup
from vethuq_core.index import (
    AlreadyRunningError,
    AmbiguousFileError,
    DatabaseIntegrityError,
    FileNotTrackedError,
    Indexing,
    IndexRunner,
    IndexRunnerError,
    IndexSubmission,
    Reindex,
    SearchIndexRebuild,
    StaleLockError,
)
from vethuq_core.ocr import Document
from vethuq_core.sources import SourceNotFoundError, Sources
from vethuq_core.storage import open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.index.panel import IndexPanel, StatePanel
from vethuq_cli.theme import Theme

app = typer.Typer(help="Run OCR indexing on registered sources.")

LANG_HELP = (
    "Read files in this language this time ('te', 'en,te', or 'auto' for every installed "
    "language), instead of each source's own languages or the 'ocr_languages' setting. Several "
    "languages are detected between. Repeat or comma-separate."
)


ONE_OFF_HELP = (
    "Run this once in its own worker process (vethuq-worker) instead of through the background "
    "service, even when the service is installed."
)


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _choose_route(one_off: bool) -> str:
    """Where to send a request: the service when it's installed, a one-off when asked for.

    When the service is installed but isn't taking jobs (stopped or paused) and there is a
    terminal to ask, the user chooses between queueing the job and running it once; without a
    terminal it is queued, which is what the service being installed means.
    """
    if one_off:
        return Indexing.VIA_ONE_OFF
    service = Indexing.service_status()
    if service is None or service.running:
        return Indexing.VIA_AUTO
    if not _is_interactive():
        return Indexing.VIA_SERVICE
    console.print(
        IndexPanel.message(
            f"The background service is {Indexing.describe_state(service)}, so a queued job "
            "waits until it is running again.",
            Theme.NOTICE,
        )
    )
    choice = Prompt.ask(
        "Queue the job for the service, or run it once now in vethuq-worker?",
        console=console,
        choices=["queue", "one-off"],
        default="queue",
    )
    return Indexing.VIA_ONE_OFF if choice == "one-off" else Indexing.VIA_SERVICE


def _languages(lang: list[str] | None) -> str | None:
    """The `--lang` values as one comma-separated string, or None when not given."""
    return ",".join(lang) if lang else None


def _report_recovery(actions: list[str]) -> None:
    """Tell the user what was recovered from a previous run that didn't exit cleanly."""
    text = Text("Recovered from a previous run that didn't exit cleanly:", style="white")
    for action in actions:
        text.append(f"\n  - {action}", style="white")
    console.print(IndexPanel.message(text, Theme.NOTICE))


def _start_and_report(
    target: str | None,
    *,
    force: bool,
    wait: bool,
    restart: bool,
    languages: str | None = None,
    one_off: bool = False,
) -> None:
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

    via = _choose_route(one_off)
    try:
        submission = Indexing.submit(
            target,
            force=force,
            restart=restart,
            via=via,
            on_recovery=_report_recovery,
            languages=languages,
        )
    except (
        AlreadyRunningError,
        StaleLockError,
        DatabaseIntegrityError,
        SourceNotFoundError,
        IndexRunnerError,
    ) as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc

    _report_submitted(submission, "restart" if restart else "index run", wait=wait)


def _report_started(pid: int, verb: str, *, wait: bool) -> None:
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


def _report_submitted(submission: IndexSubmission, verb: str, *, wait: bool) -> None:
    """Report a started worker, or a job queued for the background service."""
    if submission.pid is not None:
        _report_started(submission.pid, verb, wait=wait)
        return
    assert submission.job_id is not None
    text = Text.assemble(
        (f"Queued {verb} for the background service (job {submission.job_id}).", Theme.OK)
    )
    if submission.service_idle and submission.service is not None:
        text.append(
            f"\n\nThe service is {Indexing.describe_state(submission.service)}; the job waits "
            "until it is running. Use '",
            style="white",
        )
        text.append("vethuq background-service resume", style=Theme.COMMAND)
        text.append("' or '", style="white")
        text.append("vethuq background-service start", style=Theme.COMMAND)
        text.append("'.", style="white")
    if not wait:
        text.append("\n\nCheck progress with '", style="white")
        text.append("vethuq index status", style=Theme.COMMAND)
        text.append("'.", style="white")
        console.print(IndexPanel.message(text, Theme.OK))
        return
    console.print(IndexPanel.message(text, Theme.OK))
    if _wait_for_job(submission.job_id):
        raise typer.Exit(code=130)


def _wait_for_job(job_id: int) -> bool:
    """Block until the queued job is finished, showing the run once it starts. True if the
    user interrupted (the job stays queued; it is the service's now)."""
    from vethuq_core.background import IndexJobs

    try:
        with console.status("Waiting for the background service...", spinner_style=Theme.PRIMARY):
            while True:
                job = IndexJobs.get(job_id)
                if job is None or job.status not in ("queued", "running"):
                    break
                time.sleep(1.0)
    except KeyboardInterrupt:
        return True
    state = IndexRunner.read_state()
    if state is not None:
        storage = open_storage()
        try:
            StatePanel.print_state(storage, state)
        finally:
            storage.close()
    return False


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
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    one_off: bool = typer.Option(
        False, "--one-off", help=ONE_OFF_HELP, hidden=not Indexing.has_service()
    ),
) -> None:
    """Start OCR indexing in the background and return immediately.

    A source that's already fully indexed is still checked for files added
    or modified since the last run - genuinely new files, files whose
    content has changed (by checksum), and previously failed files are
    (re)processed; unchanged files are left untouched. Use 'vethuq index
    status' to check progress.
    """
    _start_and_report(
        target,
        force=force,
        wait=wait,
        restart=False,
        languages=_languages(lang),
        one_off=one_off,
    )


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
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    one_off: bool = typer.Option(
        False, "--one-off", help=ONE_OFF_HELP, hidden=not Indexing.has_service()
    ),
) -> None:
    """Retry only previously-failed files, in the background.

    New files and already-indexed files are left untouched - only files
    whose last OCR attempt failed are (re)processed. Use 'vethuq index run'
    instead to also pick up new files.
    """
    _start_and_report(
        target,
        force=force,
        wait=wait,
        restart=True,
        languages=_languages(lang),
        one_off=one_off,
    )


class _ImplicitSourceGroup(TyperGroup):
    """`reindex <source>` means `reindex source <source>`; `file` is reserved for `reindex file`."""

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            args = ["source", *args]
        return super().parse_args(ctx, args)


reindex_app = typer.Typer(
    cls=_ImplicitSourceGroup,
    help=(
        "Re-index everything under a source ('vethuq index reindex <source id or path>'), "
        "or one file ('vethuq index reindex file <id or path>')."
    ),
    no_args_is_help=True,
)
app.add_typer(reindex_app, name="reindex")


def _start_reindex(
    starter: Callable[[str], IndexSubmission], verb: str, *, wait: bool, one_off: bool
) -> None:
    via = _choose_route(one_off)
    try:
        submission = starter(via)
    except (
        AlreadyRunningError,
        AmbiguousFileError,
        FileNotTrackedError,
        StaleLockError,
        DatabaseIntegrityError,
        SourceNotFoundError,
        IndexRunnerError,
    ) as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc
    _report_submitted(submission, verb, wait=wait)


def _confirm_reindex_source(target: str) -> None:
    """Ask before re-indexing a whole source; exits cleanly if the answer is no."""
    storage = open_storage()
    try:
        try:
            source = Sources.get(storage, Sources.coerce(target))
        except SourceNotFoundError as exc:
            error_console.print(str(exc), style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        counts = {
            row["status"]: row["count"] for row in storage.count_document_index_by_status(source.id)
        }
    finally:
        storage.close()
    files = counts.get("indexed", 0) + counts.get("error", 0)
    if not Confirm.ask(
        f"Re-index all {files} file{'s' if files != 1 else ''} under {source.path}? "
        "Every file is OCR'd again, which can take a long time. Existing content stays "
        "searchable until each file has been reprocessed.",
        console=console,
        default=False,
    ):
        console.print(IndexPanel.message("Aborted.", "bright_black"))
        raise typer.Exit(code=0)


@reindex_app.command("source", hidden=True)
def reindex_source(
    target: str = typer.Argument(..., help="Source id or path to re-index."),
    wait: bool = typer.Option(
        False, "--wait", help="Block until the run finishes, printing progress as it goes."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Re-index without asking for confirmation, and clear a stale lock left by a run "
            "that didn't exit cleanly."
        ),
    ),
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    one_off: bool = typer.Option(
        False, "--one-off", help=ONE_OFF_HELP, hidden=not Indexing.has_service()
    ),
) -> None:
    """Re-index every file under a source, not just failed ones.

    Asks for confirmation first. Files are OCR'd again and their existing
    documents updated in place, so nothing is duplicated; a file's previous
    content stays searchable until it has been reprocessed. Use 'vethuq index
    reindex file' for a single file. With --lang the files are read in that language this
    time; to make it lasting, set it on the source ('vethuq source set-languages').
    """
    if not force:
        _confirm_reindex_source(target)
    languages = _languages(lang)
    _start_reindex(
        lambda via: Reindex.submit_source(target, force=force, languages=languages, via=via),
        "reindex",
        wait=wait,
        one_off=one_off,
    )


@reindex_app.command("file")
def reindex_file(
    file: str = typer.Argument(..., help="File id or path to re-index."),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Source id or path - required when the file sits under more than one source.",
    ),
    wait: bool = typer.Option(
        False, "--wait", help="Block until the run finishes, printing progress as it goes."
    ),
    force: bool = typer.Option(
        False, "--force", help="Clear a stale lock left by a run that didn't exit cleanly."
    ),
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    one_off: bool = typer.Option(
        False, "--one-off", help=ONE_OFF_HELP, hidden=not Indexing.has_service()
    ),
) -> None:
    """Re-index a single file, updating its existing document in place.

    With --lang the file is read in that language this time - the way to redo a file whose
    language was detected wrongly.
    """
    languages = _languages(lang)
    _start_reindex(
        lambda via: Reindex.submit_file(
            file, source=source, force=force, languages=languages, via=via
        ),
        "reindex",
        wait=wait,
        one_off=one_off,
    )


@app.command("rebuild-search")
def rebuild_search(
    force: bool = typer.Option(False, "--force", help="Rebuild without asking for confirmation."),
) -> None:
    """Rebuild the full-text search tables from the page text already stored.

    Files are not re-read or re-OCR'd. Use this if search results look incomplete
    or out of date.
    """

    if not force and not Confirm.ask(
        "Rebuild the search index? Search may be slow or incomplete until it finishes.",
        console=console,
        default=False,
    ):
        console.print(IndexPanel.message("Aborted.", "bright_black"))
        raise typer.Exit(code=0)

    with console.status("Rebuilding search index...", spinner_style=Theme.PRIMARY) as spinner:

        def progress(index: str, position: int, total: int) -> None:
            spinner.update(f"[{position}/{total}] Rebuilding {index}...")

        try:
            result = SearchIndexRebuild.run(on_progress=progress)
        except (AlreadyRunningError, StaleLockError, DatabaseIntegrityError) as exc:
            error_console.print(str(exc), style=Theme.ERROR)
            raise typer.Exit(code=getattr(exc, "exit_code", 1)) from exc

    table = IndexPanel.new_table()
    table.add_column("Index")
    table.add_column("Status")
    table.add_column("Pages", justify="right")
    table.add_column("Details")
    for index in [*result.rebuilt, *result.failed]:
        if index in result.failed:
            table.add_row(
                index,
                Text("failed", style=Theme.ERROR),
                "",
                Text(result.failed[index], style=Theme.ERROR),
            )
        else:
            table.add_row(index, Text("rebuilt", style=Theme.OK), str(result.rebuilt[index]), "")
    border = Theme.DANGER if result.failed else Theme.OK
    table.caption = Text.assemble(
        (f"{len(result.rebuilt)} rebuilt, {len(result.failed)} failed", border),
        (f" in {result.seconds:.1f}s.", "white"),
    )
    console.print(IndexPanel.table(table, "Search Index Rebuild", border_style=border))
    if result.failed:
        raise typer.Exit(code=1)


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
