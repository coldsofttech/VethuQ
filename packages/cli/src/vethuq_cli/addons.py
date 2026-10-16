"""Mounting the commands installed add-ons describe, with `CliGroup` (see `Addon.cli()`)."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import typer

from vethuq_addon_api import CliCommand, CliGroup, CliParam, CliResult
from vethuq_cli.console import Theme, console, error_console
from vethuq_cli.output import dump, table
from vethuq_cli.state import State

KINDS: dict[str, Any] = {"str": str, "int": int, "bool": bool, "path": Path}


def show(result: CliResult | str | None) -> None:
    """Print what a command returned."""
    if result is None:
        return
    if isinstance(result, str):
        result = CliResult(lines=[result], data={"message": result})
    if State.json and result.data is not None:
        dump(result.data)
    else:
        for line in result.lines:
            console.print(line)
        if result.table is not None:
            headers, rows = result.table
            table([dict(zip(headers, row, strict=False)) for row in rows], list(headers))
    if not result.ok:
        raise typer.Exit(1)


def _param(spec: CliParam) -> inspect.Parameter:
    kind = KINDS.get(spec.kind, str)
    name = spec.name.replace("-", "_")
    if spec.option or spec.kind == "bool":
        default = typer.Option(
            spec.default if spec.default is not None else (False if spec.kind == "bool" else None),
            f"--{spec.name.replace('_', '-')}",
            help=spec.help,
        )
        annotation = kind if spec.kind == "bool" or spec.default is not None else kind | None
    else:
        required = spec.required or spec.default is None and not spec.option
        default = typer.Argument(... if required else spec.default, help=spec.help)
        annotation = kind
    return inspect.Parameter(
        name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation
    )


def _callback(command: CliCommand):
    specs = list(command.params)

    def run(**values: Any) -> None:
        mapped = {spec.name: values[spec.name.replace("-", "_")] for spec in specs}
        show(command.run(State.client(), **mapped))

    run.__signature__ = inspect.Signature([_param(spec) for spec in specs])  # type: ignore[attr-defined]
    run.__name__ = command.name.replace("-", "_")
    run.__doc__ = command.help
    return run


def build(group: CliGroup) -> typer.Typer:
    """A typer app for one add-on group."""
    sub = typer.Typer(help=group.help, no_args_is_help=True, add_completion=False)
    for command in group.commands:
        sub.command(command.name, help=command.help)(_callback(command))
    for child in group.groups:
        sub.add_typer(build(child), name=child.name, help=child.help)
    return sub


def mount(app: typer.Typer, groups: Sequence[tuple[str, CliGroup]]) -> None:
    """Add every add-on group as `vethuq <name> ...`; a group that clashes with a built-in
    command, or that cannot be built, is skipped with a warning."""
    taken = {g.name for g in app.registered_groups} | {
        c.name or (c.callback.__name__ if c.callback else "") for c in app.registered_commands
    }
    for addon_id, group in groups:
        if group.name in taken:
            error_console.print(
                f"Warning: add-on {addon_id} adds '{group.name}', which already exists.",
                style=Theme.WARN,
            )
            continue
        try:
            app.add_typer(build(group), name=group.name, help=group.help)
            taken.add(group.name)
        except Exception as exc:  # noqa: BLE001 - one bad add-on must not break the CLI
            error_console.print(f"Warning: add-on {addon_id} commands skipped ({exc}).")


def _stopped_hint(info: Any) -> str:
    status = info.status.value
    if info.disabled or status == "disabled":
        return (
            "It is turned off. Turn it on with `vethuq addons enable "
            + info.id
            + "`, then restart."
        )
    if status == "incompatible":
        return f"It can't run here: {info.detail}. Install a build made for this computer."
    return f"It couldn't be loaded: {info.detail or 'unknown error'}. See `vethuq addons list`."


STOPPED_CONTEXT = {"allow_extra_args": True, "ignore_unknown_options": True}


def stopped_command(app: typer.Typer, info: Any, what: str = "commands") -> None:
    """Add a stand-in `<add-on id> ...` for an add-on that is not running. Whatever follows the name
    is ignored: any use of it explains why the add-on isn't running, and exits with status 1."""

    def explain() -> None:
        error_console.print(
            f"{info.name} isn't running, so its {what} aren't available. {_stopped_hint(info)}",
            style=Theme.WARN,
        )
        raise typer.Exit(1)

    app.command(
        info.id,
        help=f"(not running: {info.status.value}) {info.name}.",
        context_settings=STOPPED_CONTEXT,
    )(explain)


def mount_stopped(app: typer.Typer, infos: Sequence[Any]) -> None:
    """Add a stand-in `vethuq <add-on id> ...` for every installed add-on that is not running, so
    its commands are not simply missing."""
    taken = {g.name for g in app.registered_groups} | {
        c.name or (c.callback.__name__ if c.callback else "") for c in app.registered_commands
    }
    for info in infos:
        if info.status.value == "loaded" or info.id in taken:
            continue
        stopped_command(app, info)
        taken.add(info.id)
