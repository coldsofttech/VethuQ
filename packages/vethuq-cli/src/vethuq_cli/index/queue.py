"""`vethuq index queue ...`: every index request, waiting, running or finished."""

from __future__ import annotations

import json

import typer
from rich.text import Text
from vethuq_core.index import IndexJob, IndexJobs

from vethuq_cli.console import console, error_console
from vethuq_cli.export import ListExport
from vethuq_cli.index.panel import IndexPanel
from vethuq_cli.theme import Theme

app = typer.Typer(
    help="See the index runs waiting for a worker, running, or finished.", no_args_is_help=True
)

JOB_STYLES = {
    "queued": Theme.WARNING,
    "running": Theme.PRIMARY,
    "completed": Theme.SUCCESS,
    "failed": Theme.DANGER,
    "cancelled": "bright_black",
}


def _status_cell(job: IndexJob) -> Text:
    return Text(job.status, style=JOB_STYLES.get(job.status, "white"))


@app.command("list")
def queue_list(
    all_jobs: bool = typer.Option(
        False, "--all", help="Include finished jobs (completed, failed, cancelled)."
    ),
    limit: int = typer.Option(20, "--limit", min=1, help="Show at most this many jobs."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    export: ListExport.EXPORT = None,
    format_: ListExport.FORMAT = None,
) -> None:
    """List the pending jobs (waiting and running), oldest first; `--all` adds finished ones."""
    export_target = ListExport.resolve(export, format_)
    statuses = None if all_jobs else ("queued", "running")
    jobs = IndexJobs.list(statuses, limit=limit)
    if not all_jobs:
        jobs.sort(key=lambda job: job.id)
    if export_target is not None:
        ListExport.write(
            export_target,
            [{**job.to_dict(), "target": job.target or "all sources"} for job in jobs],
            [
                ("id", "Job"),
                ("status", "Status"),
                ("mode", "Kind"),
                ("target", "Target"),
                ("languages", "Languages"),
                ("requested_at", "Queued"),
                ("started_at", "Started"),
                ("finished_at", "Finished"),
                ("error", "Error"),
            ],
            title="Index queue",
            key="jobs",
            noun="job(s)",
            statuses=("status",),
            facets=("status", "mode"),
        )
        return
    if as_json:
        console.print(json.dumps([job.to_dict() for job in jobs]))
        return
    if not jobs:
        console.print(
            IndexPanel.message(
                "The queue is empty." if not all_jobs else "No job has been queued yet.",
                "bright_black",
                "Queue",
            )
        )
        return
    table = IndexPanel.new_table()
    table.add_column("Job", justify="right")
    table.add_column("Status")
    table.add_column("Kind")
    table.add_column("Target", no_wrap=False, overflow="fold")
    table.add_column("Languages")
    table.add_column("Queued")
    for job in jobs:
        table.add_row(
            str(job.id),
            _status_cell(job),
            job.mode,
            job.target or "all sources",
            job.languages or "",
            IndexPanel.friendly_time(job.requested_at),
        )
    console.print(IndexPanel.table(table, "Index Queue"))


@app.command("show")
def queue_show(
    job_id: int = typer.Argument(..., help="Job id, as shown by 'queue list'."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show one job: what it is, when it was queued and started, and how it ended."""
    job = IndexJobs.get(job_id)
    if job is None:
        error_console.print(f"No queued job has id {job_id}.", style=Theme.ERROR)
        raise typer.Exit(code=1)
    if as_json:
        console.print(json.dumps(job.to_dict()))
        return
    when = IndexPanel.friendly_time
    text = Text.assemble((f"Job {job.id}: ", "white"), _status_cell(job))
    text.append(f"\nKind: {job.mode}", style="white")
    text.append(f"\nTarget: {job.target or 'all sources'}", style="white")
    if job.languages:
        text.append(f"\nLanguages: {job.languages}", style="white")
    text.append(f"\nQueued: {when(job.requested_at)}", style="white")
    if job.started_at:
        text.append(f"\nStarted: {when(job.started_at)}", style="white")
    if job.finished_at:
        text.append(f"\nFinished: {when(job.finished_at)}", style="white")
    if job.error:
        text.append(f"\nError: {job.error}", style=Theme.ERROR)
    border = Theme.DANGER if job.status == "failed" else JOB_STYLES.get(job.status, Theme.PRIMARY)
    console.print(IndexPanel.message(text, border, "Queue"))
    if job.status == "running":
        console.print(
            IndexPanel.message(
                Text.assemble(
                    ("Progress: '", "white"),
                    ("vethuq index status", Theme.COMMAND),
                    ("'.", "white"),
                ),
                "bright_black",
                "Queue",
            )
        )
