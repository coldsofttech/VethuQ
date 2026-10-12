"""`vethuq settings`: a hierarchy built from the settings the client has.

    vethuq settings index workers auto
    vethuq settings search snippet-context-chars 120
    vethuq settings search normalize case ignore
    vethuq settings search fuzzy threshold loose        (an engine's option; the engine is a group)
    vethuq settings search noise-fuzzy noise high
    vethuq settings addons backup interval-minutes 720   (an add-on's own settings)

Giving no value shows the setting; `--reset` puts its default back. Every area is found by looking
for the `get_X` / `set_X` / `reset_X` methods of `client.settings.<area>`, so a new setting shows up
without code here; engine options and add-on settings come from the installed add-ons.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

import typer

from vethuq_cli.console import Theme
from vethuq_cli.output import cell, facts, say, table
from vethuq_cli.state import State

AREAS = (
    "search",
    "index",
    "ocr",
    "sources",
    "languages",
    "tiers",
    "metrics",
    "confidence",
    "logs",
    "updates",
    "database",
)
# Methods that take more than the value: handled by hand.
SKIP = {("search", "normalizer"), ("search", "option")}


def coerce(text: str) -> Any:
    """The value a person typed, as the setting takes it: numbers, booleans and JSON lists keep
    their type; anything else stays text."""
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered.lstrip("-").isdigit():
        return int(lowered)
    try:
        return float(lowered)
    except ValueError:
        pass
    if text[:1] in "[{":
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def leaves(settings: object) -> dict[str, tuple[Callable, Callable | None, Callable | None]]:
    """`{leaf name: (get, set, reset)}` for the settings object's `get_X` methods that take only
    a value."""
    found = {}
    for name in dir(settings):
        if not name.startswith("get_"):
            continue
        getter = getattr(settings, name)
        if inspect.signature(getter).parameters:
            continue
        leaf = name[4:]
        found[leaf] = (
            getter,
            getattr(settings, f"set_{leaf}", None),
            getattr(settings, f"reset_{leaf}", None),
        )
    return found


def attach(app: typer.Typer, name: str, help_: str, get, set_, reset) -> None:
    """Add one setting as a command `name [VALUE] [--reset]`."""

    def command(
        value: str = typer.Argument(None, help="A new value; omit to show the setting."),
        reset_flag: bool = typer.Option(False, "--reset", help="Put the default back."),
    ) -> None:
        if reset_flag:
            if reset is None:
                raise SystemExit(f"{name} cannot be reset.")
            reset()
        elif value is not None:
            if set_ is None:
                raise SystemExit(f"{name} cannot be changed.")
            set_(coerce(value))
        shown = get()
        if State.json:
            say("", data={name: shown})
        else:
            from vethuq_cli.console import console

            console.print(f"{name.replace('_', '-')}: {cell(shown)}", style=Theme.LABEL)

    command.__doc__ = help_
    app.command(name.replace("_", "-"), help=help_)(command)


def area_app(client, area: str) -> typer.Typer:
    settings = getattr(client.settings, area)
    sub = typer.Typer(help=f"{area.capitalize()} settings.", no_args_is_help=True)
    for leaf, (get, set_, reset) in sorted(leaves(settings).items()):
        if (area, leaf) in SKIP:
            continue
        doc = (inspect.getdoc(get) or "").split("\n")[0] or leaf.replace("_", " ")
        attach(sub, leaf, doc, get, set_, reset)
    if area == "search":
        _search_extras(client, sub)
    return sub


def _search_extras(client, sub: typer.Typer) -> None:
    search = client.settings.search
    normalize = typer.Typer(help="The level of a normalizer, or auto.", no_args_is_help=True)
    for info in client.search.normalizers():
        attach(
            normalize,
            info.id,
            f"The {info.id} normalizer: auto or one of {', '.join(info.levels)}.",
            lambda n=info.id: search.get_normalizer(n),
            lambda v, n=info.id: search.set_normalizer(n, str(v)),
            lambda n=info.id: search.reset_normalizer(n),
        )
    sub.add_typer(normalize, name="normalize")
    for engine in client.search.engines():
        options = engine.options
        names = list(options) if isinstance(options, dict) else [o.name for o in options]
        if not names:
            continue
        group = typer.Typer(help=f"Defaults for the {engine.id} engine.", no_args_is_help=True)
        for option in names:
            attach(
                group,
                option,
                f"{engine.id} {option}",
                lambda e=engine.id, o=option: search.get_option(e, o),
                lambda v, e=engine.id, o=option: search.set_option(e, o, str(v)),
                lambda e=engine.id, o=option: search.reset_option(e, o),
            )
        sub.add_typer(group, name=engine.id)


def addon_app(client) -> typer.Typer:
    group = typer.Typer(help="Settings of installed add-ons.", no_args_is_help=True)
    for _addon_id, spec in client.addons.cli():
        if not spec.settings:
            continue
        sub = typer.Typer(help=f"{spec.name} settings.", no_args_is_help=True)
        for setting in spec.settings:
            attach(
                sub,
                setting.name,
                setting.help,
                lambda s=setting: s.get(client),
                lambda v, s=setting: s.set(client, str(v)),
                (lambda s=setting: s.reset(client)) if setting.reset else None,
            )
        group.add_typer(sub, name=spec.name)
    return group


def location_app() -> typer.Typer:
    """`settings location`: where the data folder and the backups live."""
    from vethuq import Paths

    group = typer.Typer(help="Where VethuQ keeps its data.", no_args_is_help=True)
    backups = typer.Typer(help="Where database backups are kept.", no_args_is_help=True)
    group.add_typer(backups, name="backups")

    def attempt(action: Callable[[], Any]) -> Any:
        try:
            return action()
        except (ValueError, OSError) as error:
            say(str(error), style=Theme.ERROR)
            raise typer.Exit(1) from None

    @group.command("show")
    def show() -> None:
        """The data folder and where it comes from."""
        facts(
            {
                "path": str(Paths.data_root()),
                "source": Paths.location_source(),
                "default": str(Paths.default_data_root()),
            },
            title="Data location",
        )

    @group.command("set")
    def set_(
        path: str,
        no_move: bool = typer.Option(False, "--no-move", help="Do not move the existing data."),
    ) -> None:
        """Move the data folder to PATH (stop any indexing first)."""
        new = attempt(lambda: Paths.relocate(path, move=not no_move))
        say(f"Data location is now {new}", data={"path": str(new)})

    @group.command("reset")
    def reset(
        no_move: bool = typer.Option(False, "--no-move", help="Do not move the existing data."),
    ) -> None:
        """Go back to the default data folder."""
        new = attempt(lambda: Paths.reset_location(move=not no_move))
        say(f"Data location is now {new}", data={"path": str(new)})

    @backups.command("show")
    def backups_show() -> None:
        """The folder backups are kept in."""
        say(str(Paths.backups_dir()), data={"path": str(Paths.backups_dir())})

    @backups.command("set")
    def backups_set(path: str) -> None:
        """Keep backups in PATH."""
        new = attempt(lambda: Paths.set_backups_dir(path))
        say(f"Backups are now kept in {new}", data={"path": str(new)})

    @backups.command("reset")
    def backups_reset() -> None:
        """Keep backups next to the database again."""
        new = attempt(Paths.reset_backups_dir)
        say(f"Backups are now kept in {new}", data={"path": str(new)})

    return group


def build(client) -> typer.Typer:
    app = typer.Typer(help="Show and change settings.", no_args_is_help=True)
    for area in AREAS:
        app.add_typer(area_app(client, area), name=area)
    app.add_typer(addon_app(client), name="addons")
    app.add_typer(location_app(), name="location")

    @app.command("show")
    def show() -> None:
        """Every setting and its value."""
        rows = []
        for area in AREAS:
            for leaf, (get, _s, _r) in sorted(leaves(getattr(client.settings, area)).items()):
                rows.append({"setting": f"{area} {leaf.replace('_', '-')}", "value": get()})
        table(rows, ["setting", "value"])

    _ = facts
    return app
