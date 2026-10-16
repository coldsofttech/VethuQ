"""The `vethuq` command: groups, global options, and clean error reporting."""

from __future__ import annotations

import sys
from importlib.metadata import entry_points
from pathlib import Path

import typer

import vethuq
from vethuq import errors
from vethuq_cli import addons, commands, settings
from vethuq_cli.console import Theme, error_console
from vethuq_cli.notices import AfterCommand
from vethuq_cli.state import State


def _version(value: bool) -> None:
    if value:
        commands.show_version()
        raise typer.Exit()


def _can_interact() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _main(
    ctx: typer.Context,
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Open the interactive shell (needs vethuq-interactive-cli).",
    ),
    json: bool = typer.Option(False, "--json", help="Print results as JSON."),
    db: Path = typer.Option(None, "--db", help="Use this database file."),  # noqa: B008
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    """Run a subcommand."""
    State.json = json
    if db is not None:
        State.db_path = db
    if ctx.invoked_subcommand is not None:
        return
    # No command: the interactive shell when it is installed and this is a terminal, else help.
    if interactive or _can_interact():
        try:
            from vethuq_interactive_cli import run
        except ImportError:
            if interactive:
                raise SystemExit(
                    "The interactive shell needs: pip install vethuq-interactive-cli"
                ) from None
        else:
            run(root=ctx.find_root().command)  # type: ignore[arg-type]
            raise typer.Exit()
    typer.echo(ctx.get_help())
    raise typer.Exit()


def _mount_plugins(app: typer.Typer) -> None:
    """Commands other packages add: an entry point in the `vethuq.cli` group, named for the command
    group, that is (or returns) a typer app. A plugin that cannot load is skipped with a warning."""
    taken = {g.name for g in app.registered_groups}
    for point in entry_points(group="vethuq.cli"):
        if point.name in taken:
            continue
        try:
            plugin = point.load()
            sub = plugin() if callable(plugin) and not isinstance(plugin, typer.Typer) else plugin
            app.add_typer(sub, name=point.name)
        except Exception as exc:  # noqa: BLE001 - one bad plugin must not break the CLI
            error_console.print(
                f"Warning: commands '{point.name}' skipped ({exc}).", style=Theme.WARN
            )


def build_app() -> typer.Typer:
    """The whole command tree: the built-in groups, the settings hierarchy (it lists the installed
    engines and add-ons) and the commands installed add-ons describe."""
    app = typer.Typer(
        help=f"{vethuq.APP_NAME}: {vethuq.APP_TAGLINE}", no_args_is_help=False, add_completion=False
    )
    app.callback(invoke_without_command=True)(_main)
    commands.register(app)
    client = State.client()
    app.add_typer(settings.build(client), name="settings")
    _mount_plugins(app)
    try:
        addons.mount(app, client.addons.cli())
        addons.mount_stopped(app, client.addons.list())
    except Exception as exc:  # noqa: BLE001 - never block the built-in commands
        error_console.print(f"Warning: add-on commands unavailable ({exc}).", style=Theme.WARN)
    return app


def _early_db(argv: list[str]) -> Path | None:
    """`--db FILE` from the command line, needed before it is parsed to find the add-ons."""
    for index, arg in enumerate(argv):
        if arg == "--db" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if arg.startswith("--db="):
            return Path(arg[5:])
    return None


class Cli:
    @staticmethod
    def run(argv: list[str] | None = None) -> None:
        """Console-script entry point: run `app`, reporting errors cleanly."""
        arguments = list(sys.argv[1:] if argv is None else argv)
        try:
            State.db_path = _early_db(arguments)
            try:
                build_app()(args=arguments, prog_name="vethuq")
            except SystemExit as done:
                if done.code in (None, 0):
                    AfterCommand.print(State.client(), arguments)
                raise
        except errors.VethuQError as exc:
            error_console.print(f"Error: {exc.message}", style=Theme.ERROR)
            if getattr(exc, "hint", None):
                error_console.print(f"What to do: {exc.hint}")
            raise SystemExit(getattr(exc, "exit_code", 1) or 1) from None
        finally:
            State.close()


if __name__ == "__main__":
    Cli.run()
