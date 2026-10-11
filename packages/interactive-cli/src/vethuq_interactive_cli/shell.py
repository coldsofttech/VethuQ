"""The interactive shell: menus built from the `vethuq` command tree.

Every command group becomes a menu and every command a form whose questions come from the
command's own parameters (type, choices, default, required), so built-in commands, the settings
hierarchy and the commands installed add-ons describe all appear without code here. Search is
guided by hand, because its options depend on the engine chosen.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_cli.console import Theme, console, error_console

import vethuq
from vethuq import errors
from vethuq_interactive_cli.logo import Logo
from vethuq_interactive_cli.ui import Quit, Ui

BACK = "\x00back"
EXIT = "\x00exit"
# Shown first, in this order; every other group follows, then Version and Exit.
MAIN_ORDER = ("search", "source", "index", "settings", "stats", "db", "logs")
TITLES = {
    "source": "Sources",
    "db": "Database",
    "file-types": "File types",
    "search-engines": "Search engines",
    "search-index": "Search index",
}


def title_of(name: str) -> str:
    return TITLES.get(name, name.replace("-", " ").capitalize())


class Shell:
    def __init__(self, ui: Ui, root: Any) -> None:
        self.ui = ui
        self.root = root

    # ----- the loop -------------------------------------------------------------------------

    def run(self) -> None:
        self.banner()
        try:
            self.menu([], title="Main Menu")
        except Quit:
            pass
        console.print()
        console.print("Goodbye.", style=Theme.DIM)

    def banner(self) -> None:
        content: Table | str = ""
        if console.color_system is not None:
            content = Table.grid(padding=(0, 2))
            content.add_column(no_wrap=True)
            content.add_column(vertical="middle")
            content.add_row(
                Text.from_markup(Logo.markup()),
                Text.assemble(
                    (f"{vethuq.APP_NAME}\n", "bold cyan"), (vethuq.APP_TAGLINE, Theme.DIM)
                ),
            )
        framed = content == ""
        console.print(
            Panel(
                content,
                title=Text(vethuq.APP_NAME, style="bold cyan") if framed else None,
                title_align="left",
                subtitle=Text(vethuq.APP_TAGLINE, style=Theme.DIM) if framed else None,
                subtitle_align="left",
                border_style="cyan",
                expand=True,
            )
        )

    # ----- the command tree -----------------------------------------------------------------

    # typer ships its own copy of click, so a command is recognised by what it has, not by class.
    @staticmethod
    def is_group(node: Any) -> bool:
        return hasattr(node, "list_commands")

    def node(self, path: list[str]) -> Any:
        node = self.root
        for name in path:
            node = node.get_command(typer.Context(node), name)
        return node

    @staticmethod
    def children(group: Any) -> list[Any]:
        ctx = typer.Context(group)
        found = []
        for name in group.list_commands(ctx):
            command = group.get_command(ctx, name)
            if command is not None and not command.hidden:
                found.append(command)
        return found

    def menu(self, path: list[str], title: str) -> None:
        """Show the menu of the group at `path` until Back (or Exit at the top)."""
        group = self.node(path)
        while True:
            items = self.items(path, group)
            choice = self.ui.select(title, items)
            if choice in (BACK, EXIT):
                return
            if choice == "search" and not path:
                self.guard(self.search)
                continue
            if choice == "version" and not path:
                self.guard(lambda: self.invoke(["version"]))
                continue
            child = self.node([*path, choice])
            if self.is_group(child):
                self.menu([*path, choice], title_of(choice) if not path else f"{title} › {choice}")
            else:
                self.guard(lambda child=child, choice=choice: self.command(path, child))

    def items(self, path: list[str], group: Any) -> list[tuple[str, str]]:
        commands = {c.name: c for c in self.children(group)}
        names = list(commands)
        if not path:
            first = [n for n in MAIN_ORDER if n in commands]
            rest = [n for n in names if n not in first and n != "version"]
            names = [*first, *rest, "version"] if "version" in commands else [*first, *rest]
        items = []
        for name in names:
            label = title_of(name) if not path else name
            help_ = (commands[name].get_short_help_str(limit=70) or "").strip()
            items.append((name, f"{label} - {help_}" if help_ and path else label))
        items.append((EXIT, "Exit") if not path else (BACK, "Back"))
        return items

    # ----- running a command ----------------------------------------------------------------

    def command(self, path: list[str], command: Any) -> None:
        args = self.ask(command)
        if args is None:
            return
        self.invoke([*path, str(command.name), *args])

    def ask(self, command: Any) -> list[str] | None:
        """Ask for the command's parameters and return the arguments for it."""
        arguments: list[str] = []
        options = [p for p in command.params if self.is_option(p) and p.name != "help"]
        for param in command.params:
            if not self.is_option(param):
                value = self.value(param)
                arguments += self.render_argument(param, value)
        required = [p for p in options if p.required]
        optional = [p for p in options if not p.required]
        chosen = list(required)
        if optional and self.ui.confirm("Set optional options?", default=False):
            chosen += optional
        flags: list[str] = []
        for param in chosen:
            flags += self.render_option(param, self.value(param))
        return [*flags, *arguments]

    def label(self, param: Any) -> str:
        help_ = getattr(param, "help", None)
        name = param.human_readable_name.replace("_", " ")
        hint = "" if param.required else " (blank to skip)"
        return f"{name}{' - ' + help_ if help_ else ''}{hint}"

    def value(self, param: Any) -> Any:
        """Ask for one parameter, in the way its type suggests; None means 'not given'."""
        kind = param.type
        if self.is_option(param) and param.is_flag:
            return self.ui.confirm(self.label(param), default=bool(param.default))
        if hasattr(kind, "choices"):
            choices = [(c, c) for c in kind.choices]
            if not param.required:
                choices.insert(0, ("", "(skip)"))
            return self.ui.select(self.label(param), choices) or None
        default = (
            param.default if param.default not in (None, ()) and not callable(param.default) else ""
        )
        while True:
            raw = self.ui.text(self.label(param), default="" if default is None else str(default))
            raw = raw.strip()
            if not raw:
                if param.required:
                    console.print("This one is required.", style=Theme.WARN)
                    continue
                return None
            try:
                multiple = param.multiple or getattr(param, "nargs", 1) == -1
                parts = raw.replace(",", " ").split() if multiple else [raw]
                for part in parts:
                    kind.convert(part, param, typer.Context(self.root))
                return parts if multiple else parts[0]
            except Exception as exc:  # noqa: BLE001 - a click BadParameter, of whichever click
                if not hasattr(exc, "format_message"):
                    raise
                console.print(exc.format_message(), style=Theme.WARN)

    @staticmethod
    def is_option(param: Any) -> bool:
        return getattr(param, "param_type_name", "") == "option"

    @staticmethod
    def render_argument(param: Any, value: Any) -> list[str]:
        if value is None:
            return []
        return list(value) if isinstance(value, list) else [str(value)]

    @staticmethod
    def render_option(param: Any, value: Any) -> list[str]:
        if value is None:
            return []
        flag = param.opts[0]
        if param.is_flag:
            if value == bool(param.default):
                return []
            if value:
                return [flag]
            return [param.secondary_opts[0]] if param.secondary_opts else []
        values = value if isinstance(value, list) else [value]
        return [part for v in values for part in (flag, str(v))]

    def invoke(self, argv: list[str]) -> None:
        """Run `vethuq <argv>` in this process; whatever goes wrong is printed, never raised."""
        try:
            self.root.main(args=argv, prog_name="vethuq", standalone_mode=False)
        except typer.Exit:
            return
        except errors.VethuQError as exc:
            error_console.print(f"Error: {exc.message}", style=Theme.ERROR)
            if getattr(exc, "hint", None):
                error_console.print(f"What to do: {exc.hint}")
        except SystemExit as exc:
            if exc.code not in (0, None):
                error_console.print(f"Error: {exc.code}", style=Theme.ERROR)
        except Exception as exc:  # noqa: BLE001 - a usage error from click, or anything else
            message = exc.format_message() if hasattr(exc, "format_message") else str(exc)
            error_console.print(f"Error: {message}", style=Theme.ERROR)

    def guard(self, action: Any) -> None:
        try:
            action()
        except Quit:
            raise
        except KeyboardInterrupt:
            console.print()
        except Exception as exc:  # noqa: BLE001 - keep the shell alive
            error_console.print(f"Error: {exc}", style=Theme.ERROR)

    # ----- search ---------------------------------------------------------------------------

    def search(self) -> None:
        from vethuq_cli.state import State

        client = State.client()
        query = ""
        while not query:
            query = self.ui.text("Search for").strip()
        engines = [e for e in client.search.engines() if e.available]
        choices = [
            ("", "Default engine"),
            ("all", "All engines"),
            ("hybrid", "Hybrid (meaning + words)"),
        ]
        choices += [(e.id, f"{e.id} - {e.label}") for e in engines]
        engine = self.ui.select("Engine", choices)
        argv = ["search", query]
        if engine:
            argv += ["--engine", engine]
            info = next((e for e in engines if e.id == engine), None)
            options = getattr(info, "options", None) or {}
            names = list(options.keys()) if isinstance(options, dict) else [o.name for o in options]
            for name in names:
                default = options.get(name, "") if isinstance(options, dict) else ""
                value = self.ui.text(
                    f"{engine} {name} (blank for the default)", default=str(default or "")
                )
                if value.strip() and value.strip() != str(default or ""):
                    argv += ["--option", f"{engine}.{name}={value.strip()}"]
        if self.ui.confirm("Match case?", default=False):
            argv.append("--case-sensitive")
        languages = self.ui.text("Languages (space separated, blank for all)").split()
        for language in languages:
            argv += ["--language", language]
        self.invoke(argv)
