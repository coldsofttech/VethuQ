"""`vethuq logs` command for reading VethuQ's log files."""

from __future__ import annotations

import html
from collections import deque
from collections.abc import Iterable
from pathlib import Path

import typer
from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.hints import Hints
from vethuq_core.logs import LogNotFoundError, Logs
from vethuq_core.search import Export
from vethuq_core.storage import default_db_path

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme


class LogsCommand:
    EXPORT_FORMATS = ("text", "json", "html")

    DEFAULT_TAIL = 40

    class _FollowView:
        """A panel of the newest log entries that fit the terminal, for `rich.live.Live`.

        Older entries drop off the top as new ones arrive, so a long stream never
        outgrows the screen.
        """

        MAX_KEPT = 500

        def __init__(self, title: str, records: Iterable[str] = ()) -> None:
            self._title = title
            self._records: deque[str] = deque(records, maxlen=LogsCommand._FollowView.MAX_KEPT)

        def add(self, record: str) -> None:
            self._records.append(record)

        def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
            inner = options.update(width=max(options.max_width - 4, 10), height=None)
            max_rows = max((options.height or console.height) - 2, 1)
            kept: list[Text] = []
            rows = 0
            for record in reversed(self._records):
                text = Text(
                    record,
                    style=LogsCommand._style_for(record) or "white",
                    no_wrap=False,
                    overflow="fold",
                )
                height = len(console.render_lines(text, inner, pad=False))
                if kept and rows + height > max_rows:
                    break
                kept.append(text)
                rows += height
            body: Text = (
                Text("\n").join(reversed(kept))
                if kept
                else Text("Waiting for new log entries...", style="bright_black")
            )
            yield Panel(
                body,
                title=self._title,
                title_align="left",
                border_style=Theme.PRIMARY,
                expand=True,
            )

    HELP = (
        "Show the most recent entries of VethuQ's log files. Without a COMPONENT, lists "
        "the log files.\n\n"
        "Components:\n\n"
        "database - the database: opening it, schema upgrades and backups, integrity "
        "checks, write failures and failed searches.\n\n"
        "index - indexing: when the index worker starts and stops, each source scan and what "
        "it found, duplicates skipped, retries, and OCR, text-extraction and indexing "
        "failures with the file, page and reason.\n\n"
        "ui - the VethuQ desktop app: when it starts and stops, and anything that went "
        "wrong in it.\n\n"
        "cli - the `vethuq` command line: each command that ran, and how it finished (exit "
        "code and how long it took).\n\n"
        "--level - only show entries at or above a level; entries below it are hidden:\n\n"
        "debug - everything: fine-grained detail as well as all the levels below.\n\n"
        "info - normal progress (scans, indexing, startup and shutdown) plus warnings and "
        "errors.\n\n"
        "warning - things that went wrong but were handled, such as a retry, plus errors.\n\n"
        "error - only failures. A good first look when something isn't working.\n\n"
        "A level can only show what was recorded, so entries below the level set with `vethuq "
        "settings logs level` are never in the file.\n\n"
        "--export FILE - write the selected entries to FILE as plain text, one entry per line "
        "(a traceback stays with the entry that raised it), instead of printing them; "
        "--format json or html writes them as a table instead. "
        "It uses the same selection as printing - the component, --tail, --level and --date - "
        "so `--level error --export errors.txt` saves just the errors. An existing FILE is "
        "overwritten, and --export can't be combined with --follow.\n\n"
        "Each component has its own file, one per day; how much is recorded depends on "
        "`vethuq settings logs level` and how many days are kept on `vethuq settings logs "
        "retention`."
    )

    @staticmethod
    def _style_for(record: str) -> str | None:
        level = Logs.level_of(record)
        if level == "error":
            return Theme.ERROR
        if level == "warning":
            return Theme.WARNING
        return None

    @staticmethod
    def _fail(message: str) -> typer.Exit:
        error_console.print(f"Error: {message}", style=Theme.ERROR)
        return typer.Exit(code=1)

    @staticmethod
    def _list_components(db_path: Path) -> None:
        table = Table(
            box=box.SIMPLE, header_style=f"bold {Theme.PRIMARY}", border_style=Theme.PRIMARY
        )
        table.add_column("Component", style=Theme.LABEL)
        # The shared console is soft-wrapping, which would crop a long path.
        table.add_column("Log file", no_wrap=False, overflow="fold")
        for component in Logs.COMPONENTS:
            table.add_row(component, str(Logs.log_file(component, db_path)))
        hint = Text.assemble(
            ("Read one with ", "white"),
            (Hints.command("vethuq logs <component> --tail 40"), Theme.COMMAND),
            (".", "white"),
        )
        console.print(
            Panel(
                Group(table, hint),
                title="Logs",
                title_align="left",
                border_style=Theme.PRIMARY,
                expand=True,
            )
        )

    @staticmethod
    def _panel(message: str | Text, title: str, border_style: str) -> Panel:
        """A full-width panel with a left-aligned `title`; `message` wraps rather than crops."""
        text = Text(message, style="white") if isinstance(message, str) else message
        # The shared console is soft-wrapping, which would crop long lines in a panel.
        text.no_wrap = False
        text.overflow = "fold"
        return Panel(text, title=title, title_align="left", border_style=border_style, expand=True)

    @staticmethod
    def run(
        component: str | None = typer.Argument(
            None,
            metavar="[COMPONENT]",
            help=f"One of: {', '.join(Logs.COMPONENTS)}. Omit to list the log files.",
        ),
        tail: int = typer.Option(
            DEFAULT_TAIL, "--tail", "-n", help="Number of most recent log entries to show."
        ),
        follow: bool = typer.Option(
            False, "--follow", "-f", help="Keep printing new entries as they're written."
        ),
        level: str | None = typer.Option(
            None,
            "--level",
            help=f"Only show entries at or above this level: {', '.join(Logs.LEVELS)}.",
        ),
        day: str | None = typer.Option(
            None,
            "--date",
            help="Read a past day's log (YYYY-MM-DD) instead of today's.",
        ),
        export: str | None = typer.Option(
            None, "--export", help="Write the selected entries to this file instead of printing."
        ),
        format_: str | None = typer.Option(
            None,
            "--format",
            help=(
                "Export format: 'text' (one entry per line, the default), 'json' or 'html' "
                "(a table of time, level, thread, logger and message). Only used with --export."
            ),
        ),
    ) -> None:
        """Show the most recent entries of VethuQ's log files (database, index, ui, cli)."""
        if format_ is not None and export is None:
            raise LogsCommand._fail("--format needs --export.")
        if format_ is not None and format_ not in LogsCommand.EXPORT_FORMATS:
            raise LogsCommand._fail(
                f"--format must be one of: {', '.join(LogsCommand.EXPORT_FORMATS)}."
            )
        db_path = default_db_path()
        if component is None:
            LogsCommand._list_components(db_path)
            return
        try:
            selected_day = Logs.validate_request(
                component, level=level, lines=tail, day=day, follow=follow, export=export
            )
        except ValueError as exc:
            raise LogsCommand._fail(str(exc)) from exc

        try:
            records = Logs.tail(component, db_path, lines=tail, level=level, day=selected_day)
        except LogNotFoundError as exc:
            if not follow:
                raise LogsCommand._fail(str(exc)) from exc
            records = []

        if export is not None:
            if format_ in ("json", "html"):
                parsed = [Logs.parse(record) for record in records]
                Export.records(
                    parsed,
                    [
                        ("time", "Time"),
                        ("level", "Level"),
                        ("thread", "Thread"),
                        ("logger", "Logger"),
                        ("message", "Message"),
                    ],
                    Path(export),
                    format_,
                    title=f"{component.title()} log",
                    key="entries",
                    statuses=("level",),
                    facets=("level", "logger"),
                    formats={
                        "message": lambda v: f'<span class="msg">{html.escape(str(v))}</span>'
                    },
                )
                written = len(parsed)
            else:
                written = Logs.export(records, export)
            console.print(
                LogsCommand._panel(
                    Text.assemble(
                        ("Wrote ", "white"),
                        (str(written), Theme.VALUE),
                        (" entries to ", "white"),
                        (export, "white"),
                        (".", "white"),
                    ),
                    f"{component.title()} Log",
                    Theme.OK,
                )
            )
            return

        title = f"{component.title()} Log"
        if follow:
            view = LogsCommand._FollowView(f"{title} (following - Ctrl+C to stop)", records)
            try:
                with Live(view, console=console, auto_refresh=False) as live:
                    for record in Logs.follow(component, db_path, level=level):
                        view.add(record)
                        live.refresh()
            except KeyboardInterrupt:
                pass
            return
        if records:
            entries = Text("\n").join(
                Text(record, style=LogsCommand._style_for(record) or "white") for record in records
            )
            console.print(LogsCommand._panel(entries, title, Theme.PRIMARY))
        else:
            console.print(LogsCommand._panel("No log entries to show.", title, "bright_black"))
