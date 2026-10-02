"""`vethuq logs` command for reading VethuQ's log files."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from rich.table import Table
from rich.text import Text
from vethuq_core.db import Db
from vethuq_core.logs import LogNotFoundError, Logs

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme


class LogsCommand:
    DEFAULT_TAIL = 40

    @staticmethod
    def _style_for(record: str) -> str | None:
        match = Logs._RECORD_START.match(record)
        level = match.group(1).lower() if match else ""
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
        table = Table.grid(padding=(0, 2))
        table.add_column(style=Theme.LABEL)
        table.add_column()
        for component in Logs.COMPONENTS:
            table.add_row(component, str(Logs.log_file(component, db_path)))
        console.print(table)
        console.print()
        console.print(
            Text.assemble(
                "Read one with ",
                ("vethuq logs <component> --tail 40", Theme.COMMAND),
                ".",
            )
        )

    @staticmethod
    def _print(record: str) -> None:
        console.print(Text(record, style=LogsCommand._style_for(record) or ""))

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
    ) -> None:
        """Show the most recent entries of VethuQ's log files (database, index, ui, cli)."""
        db_path = Db.default_db_path()
        if component is None:
            LogsCommand._list_components(db_path)
            return
        if component not in Logs.COMPONENTS:
            raise LogsCommand._fail(
                f"unknown component {component!r}; choose one of: {', '.join(Logs.COMPONENTS)}"
            )
        if level is not None and level not in Logs.LEVELS:
            raise LogsCommand._fail(f"level must be one of: {', '.join(Logs.LEVELS)}")
        if tail < 1:
            raise LogsCommand._fail("--tail must be at least 1")
        selected_day: date | None = None
        if day is not None:
            try:
                selected_day = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                raise LogsCommand._fail("--date must be in YYYY-MM-DD format") from None
        if follow and (selected_day is not None or export is not None):
            raise LogsCommand._fail("--follow can't be combined with --date or --export")

        try:
            records = Logs.tail(component, db_path, lines=tail, level=level, day=selected_day)
        except LogNotFoundError as exc:
            if not follow:
                raise LogsCommand._fail(str(exc)) from exc
            records = []

        if export is not None:
            Path(export).write_text(
                "\n".join(records) + ("\n" if records else ""), encoding="utf-8"
            )
            console.print(
                Text.assemble(
                    "Wrote ", (str(len(records)), Theme.VALUE), " entries to ", export, "."
                )
            )
            return

        for record in records:
            LogsCommand._print(record)
        if follow:
            try:
                for record in Logs.follow(component, db_path, level=level):
                    LogsCommand._print(record)
            except KeyboardInterrupt:
                pass
