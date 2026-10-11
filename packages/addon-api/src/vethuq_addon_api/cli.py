"""What an add-on adds to the `vethuq` command line, described without any CLI library.

`Addon.cli()` returns a `CliGroup`; the CLI mounts it as `vethuq <group name> ...` and its
`settings` under `vethuq settings addons <group name> ...`. A command is run with the VethuQ client
and the values of its parameters, and answers with a `CliResult` (or a string, or `None`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CliCommand",
    "CliGroup",
    "CliParam",
    "CliResult",
    "CliSetting",
    "licence_commands",
]


@dataclass(frozen=True)
class CliParam:
    """A parameter of a command: a positional argument, or an `--option` when `option` is True.

    `kind` is `str`, `int`, `bool` (a flag) or `path`. A parameter with a `default` is optional."""

    name: str
    help: str = ""
    kind: str = "str"
    option: bool = False
    default: Any = None
    required: bool = False
    choices: Sequence[str] = ()


@dataclass(frozen=True)
class CliResult:
    """What a command shows: `lines` of text, and/or a `table` of `(headers, rows)`. `data` is
    what `--json` prints instead (a dict or list); without it the lines and table are shown."""

    lines: Sequence[str] = ()
    table: tuple[Sequence[str], Sequence[Sequence[object]]] | None = None
    data: Any = None
    ok: bool = True  # False makes the command exit with status 1


@dataclass(frozen=True)
class CliCommand:
    """A command: `run(client, **values)` gets one value per parameter, by name."""

    name: str
    help: str
    run: Callable[..., CliResult | str | None]
    params: Sequence[CliParam] = ()


@dataclass(frozen=True)
class CliSetting:
    """A setting the CLI shows, changes and resets. `get(client)` returns its value as text;
    `set(client, value)` raises an exception (shown as an error) for a value it refuses."""

    name: str
    help: str
    get: Callable[[Any], str]
    set: Callable[[Any, str], object]
    reset: Callable[[Any], object] | None = None
    choices: Sequence[str] = ()


@dataclass(frozen=True)
class CliGroup:
    """A group of commands (`vethuq backup ...`), with nested groups and its settings."""

    name: str
    help: str = ""
    commands: Sequence[CliCommand] = ()
    groups: Sequence[CliGroup] = ()
    settings: Sequence[CliSetting] = field(default_factory=tuple)


def licence_commands(public: Callable[[Any], Any], label: str) -> CliGroup:
    """`licence show|set|remove` for a licensed add-on whose public class (`Telugu(client)`) has
    `licence()`, `set_licence(token)` and `remove_licence()`."""

    def show(client: Any) -> CliResult:
        licence = public(client).licence()
        text = f"{label}: {'licensed' if licence.ok else 'not licensed'} ({licence.status.value})"
        return CliResult(
            lines=[text],
            data={"licensed": licence.ok, "status": licence.status.value},
            ok=licence.ok,
        )

    def set_(client: Any, token: str) -> CliResult:
        licence = public(client).set_licence(token)
        return CliResult(lines=[f"{label}: licence installed ({licence.status.value})."])

    def remove(client: Any) -> str:
        public(client).remove_licence()
        return f"{label}: licence removed."

    return CliGroup(
        "licence",
        f"The {label} licence.",
        commands=(
            CliCommand("show", "Show whether the licence is valid.", show),
            CliCommand(
                "set",
                "Install a licence token.",
                set_,
                (CliParam("token", "The licence token.", required=True),),
            ),
            CliCommand("remove", "Remove the installed licence.", remove),
        ),
    )
