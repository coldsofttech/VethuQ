"""`vethuq background-service ...` commands: run indexing through a background service."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.prompt import Prompt
from rich.text import Text
from vethuq_core.background import (
    BackgroundService,
    BackgroundServiceError,
    Dispatch,
    IndexJobs,
    ServiceState,
    ServiceStatus,
)
from vethuq_core.index import IndexRunner
from vethuq_core.storage import open_storage
from vethuq_core.updates import UpdateChecker, UpdateResult, UpdateStatus

from vethuq_cli.console import console, error_console
from vethuq_cli.index.panel import IndexPanel
from vethuq_cli.theme import Theme

app = typer.Typer(
    help=(
        "Run indexing through a background service. Once installed, every 'vethuq index' "
        "command queues its work for the service instead of starting its own worker."
    ),
    no_args_is_help=True,
)

TITLE = "Background Service"
STATE_STYLES = {
    ServiceState.RUNNING: Theme.SUCCESS,
    ServiceState.PAUSED: Theme.WARNING,
    ServiceState.STOPPED: Theme.DANGER,
    ServiceState.NOT_INSTALLED: "bright_black",
    ServiceState.UNSUPPORTED: "bright_black",
}


def _perform(action: str, done: str, **options: object) -> None:
    try:
        status = BackgroundService.perform(action, **options)  # type: ignore[arg-type]
    except BackgroundServiceError as exc:
        error_console.print(str(exc), style=Theme.ERROR)
        raise typer.Exit(code=1) from exc
    console.print(IndexPanel.message(f"{done} (now {status.state}).", Theme.OK, TITLE))


def _is_interactive() -> bool:
    return bool(sys.stdin) and sys.stdin.isatty()


@app.command("install")
def install(
    account: str | None = typer.Option(
        None,
        "--account",
        help=(
            "Windows account to run the service as (DOMAIN\\user). Default: you, asked for "
            "interactively. Its password is asked for in the administrator window."
        ),
    ),
    system: bool = typer.Option(
        False,
        "--system",
        help="Windows: run as LocalSystem, with no password. It can't reach mapped drives or "
        "your own folders, so sources there are not indexed.",
    ),
    home: Path | None = typer.Option(  # noqa: B008
        None,
        "--home",
        help=(
            "Data folder the service works on. Default: this user's own (the one 'vethuq "
            "settings location show' prints)."
        ),
    ),
) -> None:
    """Install the service, start it, and have it start with the computer.

    It is never installed automatically; this (or the desktop app's Index > Service) is how it
    gets set up. On Windows it asks which account to run the service as (default: you), then
    for administrator permission (UAC) and that account's password. The service works on your
    data folder and database, so every setting applies to its runs as it does to any other.
    """
    if BackgroundService.backend() == "windows" and not system and account is None:
        default = BackgroundService.current_account()
        account = (
            Prompt.ask(
                "Run the service as which Windows account?", console=console, default=default
            )
            if _is_interactive()
            else default
        )
    _perform(
        "install",
        "Installed and started the background service",
        account=account,
        system=system,
        home=home,
    )
    console.print(
        IndexPanel.message(
            "Indexing now goes through the service. Add '--one-off' to an index command to run "
            "it once without the service.",
            "bright_black",
            TITLE,
        )
    )


@app.command("uninstall")
def uninstall() -> None:
    """Stop and remove the service. Index commands run their own worker again.

    Jobs still waiting in the queue stay there and run if the service is installed again.
    """
    _perform("uninstall", "Removed the background service")


@app.command("start")
def start() -> None:
    """Start the service."""
    _perform("start", "Started the background service")


@app.command("stop")
def stop() -> None:
    """Stop the service. A run in progress is stopped and picked up again on the next start."""
    _perform("stop", "Stopped the background service")


@app.command("restart")
def restart() -> None:
    """Stop and start the service."""
    _perform("restart", "Restarted the background service")


@app.command("pause")
def pause() -> None:
    """Pause the service: the run in progress pauses and queued jobs wait."""
    _perform("pause", "Paused the background service")


@app.command("resume")
def resume() -> None:
    """Resume a paused service."""
    _perform("resume", "Resumed the background service")


def _status_text(status: ServiceStatus) -> Text:
    style = STATE_STYLES.get(status.state, "white")
    text = Text.assemble(("Service: ", "white"), (status.state, style))
    if status.installed:
        if status.start_type:
            text.append(f"\nStarts: {status.start_type}", style="white")
        if status.account:
            text.append(f"\nRuns as: {status.account}", style="white")
        if status.home:
            text.append(f"\nData folder: {status.home}", style="white")
    elif status.supported:
        text.append("\n\nInstall it with '", style="white")
        text.append("vethuq background-service install", style=Theme.COMMAND)
        text.append("'.", style="white")
    else:
        text.append("\n\nThis system has neither Windows services nor systemd.", style="white")
    return text


def _update_status() -> UpdateResult | None:
    """What the saved policy says about this version, or None. Never prompts and never updates."""
    try:
        storage = open_storage()
        try:
            return UpdateChecker.status(storage)
        finally:
            storage.close()
    except Exception:  # noqa: BLE001 - status must work even when the update check can't
        return None


@app.command("status")
def status(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show whether the service is installed and running, and what it has queued."""
    service = BackgroundService.status()
    queued = IndexJobs.queued() if service.installed else []
    state = IndexRunner.read_state()
    update = _update_status()
    if as_json:
        console.print(
            json.dumps(
                {
                    "service": service.to_dict(),
                    "queued": [job.to_dict() for job in queued],
                    "run": json.loads(state.to_json()) if state is not None else None,
                    "update": update.to_dict() if update is not None else None,
                }
            )
        )
        return
    text = _status_text(service)
    if service.installed and Dispatch.service_status() is None:
        text.append(
            "\n\nThis service works on a different data folder than this session's, so index "
            "commands here run their own worker.",
            style=Theme.NOTICE,
        )
    if service.installed:
        text.append(f"\nQueued jobs: {len(queued)}", style="white")
        if state is not None and state.is_active:
            text.append(
                f"\nRunning now: run {state.run_id} "
                f"({state.processed_files}/{state.total_files} files, {state.status})",
                style="white",
            )
            text.append("\n\nDetails: '", style="white")
            text.append("vethuq index status", style=Theme.COMMAND)
            text.append("'.", style="white")
    if update is not None and update.status in (UpdateStatus.AVAILABLE, UpdateStatus.BELOW_MINIMUM):
        # Shown whatever the notice settings say; the service itself never updates.
        text.append(f"\n\nUpdate: {update.message}", style=Theme.NOTICE)
    console.print(IndexPanel.message(text, STATE_STYLES.get(service.state, Theme.PRIMARY), TITLE))
    if queued:
        table = IndexPanel.new_table()
        table.add_column("Job", justify="right")
        table.add_column("Kind")
        table.add_column("Target", no_wrap=False, overflow="fold")
        table.add_column("Languages")
        table.add_column("Queued")
        for job in queued:
            table.add_row(
                str(job.id),
                job.mode,
                job.target or "all sources",
                job.languages or "",
                IndexPanel.friendly_time(job.requested_at),
            )
        console.print(IndexPanel.table(table, "Queued Index Jobs"))
