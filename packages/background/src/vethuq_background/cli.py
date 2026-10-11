"""`vethuq background ...`: install and control the background service."""

from __future__ import annotations

import typer
from vethuq_cli.console import Theme
from vethuq_cli.output import facts, say
from vethuq_cli.state import State

from vethuq_background.host import ServiceHost
from vethuq_background.service import BackgroundService, BackgroundServiceError

app = typer.Typer(
    help=(
        "Index through a background service. Once installed, 'vethuq index run' and its relatives "
        "queue their work for it (add --one-off to run one here)."
    ),
    no_args_is_help=True,
)


def service() -> BackgroundService:
    client = State.client()
    return BackgroundService(client.db_path, client.index.queue.control_file())


def perform(action: str, done: str, **options: object) -> None:
    try:
        status = service().perform(action, **options)
    except BackgroundServiceError as exc:
        raise SystemExit(str(exc)) from exc
    say(f"{done} (now {status.state}).", style=Theme.OK, data=status.to_dict())


@app.command("install")
def install(
    account: str = typer.Option(
        None, "--account", help="Windows: the account to run as (DOMAIN\\user)."
    ),
    password: str = typer.Option(
        None, "--password", help="Windows: that account's password.", hide_input=True
    ),
    system: bool = typer.Option(
        False, "--system", help="Windows: run as LocalSystem (no password)."
    ),
) -> None:
    """Install the service, start it, and have it start with the computer."""
    perform(
        "install",
        "Installed and started the background service",
        account=account,
        password=password,
        system=system,
    )


@app.command("uninstall")
def uninstall() -> None:
    """Stop and remove the service. Index commands run their own worker again."""
    perform("uninstall", "Removed the background service")


@app.command("start")
def start() -> None:
    """Start the installed service."""
    perform("start", "Started the background service")


@app.command("stop")
def stop() -> None:
    """Stop the service (a request being worked is asked to stop)."""
    perform("stop", "Stopped the background service")


@app.command("restart")
def restart() -> None:
    """Stop and start the service."""
    perform("restart", "Restarted the background service")


@app.command("pause")
def pause() -> None:
    """Pause the service: the run going now pauses, and no request is taken."""
    perform("pause", "Paused the background service")


@app.command("resume")
def resume() -> None:
    """Resume a paused service."""
    perform("resume", "Resumed the background service")


@app.command("status")
def status() -> None:
    """Whether the service is installed and running, and what it serves."""
    facts(service().status())


@app.command("host")
def host(
    once: bool = typer.Option(False, "--once", help="Work what is waiting, then exit."),
) -> None:
    """Work the queue here, in this terminal (what the service does in the background)."""
    worker = ServiceHost(State.client())
    worker.install_signal_handlers()
    worked = worker.run(once=once)
    say(f"Worked {worked} request(s).", style=Theme.OK, data={"worked": worked})
