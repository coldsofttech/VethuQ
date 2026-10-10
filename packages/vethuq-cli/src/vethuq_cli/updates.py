"""`vethuq updates ...` commands and the one-line notice after a command.

`vethuq settings updates ...` configures the check (on / notify-only / off, snooze, skip).
"""

from __future__ import annotations

import json
import sys

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.logs import Logs
from vethuq_core.settings import UpdateSettings
from vethuq_core.storage import open_storage
from vethuq_core.updates import UpdateChecker, UpdateResult, UpdateStatus

from vethuq_cli.console import console
from vethuq_cli.theme import Theme

app = typer.Typer(help="See whether a newer VethuQ is available, or check now.")


class UpdatesCommand:
    TITLE = "Updates"

    STATES = {
        UpdateStatus.DISABLED: "the update check is off",
        UpdateStatus.UP_TO_DATE: "up to date",
        UpdateStatus.AVAILABLE: "a newer version is available",
        UpdateStatus.BELOW_MINIMUM: "older than the minimum supported version",
        UpdateStatus.UNKNOWN: "unknown (no signed policy yet, or no version to compare)",
    }

    @staticmethod
    def logger():  # noqa: ANN205 - a stdlib logger
        return Logs.get_logger("cli")

    @staticmethod
    def rows(result: UpdateResult) -> list[tuple[str, str]]:
        mode = result.mode
        if result.disabled_by_environment:
            mode = f"off ({UpdateSettings.ENV_VAR} is set)"
        rows = [
            ("Update check", mode),
            ("Installed", result.current),
            ("Status", UpdatesCommand.STATES[result.status]),
        ]
        if result.latest:
            rows.append(("Latest", result.latest))
        if result.minimum_supported:
            rows.append(("Minimum supported", result.minimum_supported))
        if result.release_notes_url:
            rows.append(("Release notes", result.release_notes_url))
        if result.snoozed:
            rows.append(("Reminders", "snoozed"))
        if result.skipped:
            rows.append(("Skipped", f"{result.latest} will not be announced"))
        if result.policy_update_required:
            rows.append(("Policy", result.POLICY_MESSAGE))
        return rows

    @staticmethod
    def panel(result: UpdateResult) -> Panel:
        table = Table.grid(padding=(0, 2))
        for label, value in UpdatesCommand.rows(result):
            table.add_row(Text(label, style="bold"), Text(value))
        return Panel(
            table,
            title=Text(UpdatesCommand.TITLE),
            title_align="left",
            border_style=Theme.PRIMARY,
            expand=True,
        )

    @staticmethod
    def report(result: UpdateResult, as_json: bool) -> None:
        if as_json:
            console.print(json.dumps(result.to_dict()))
        else:
            console.print(UpdatesCommand.panel(result))


@app.command("status")
def status(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show what the saved policy says about this version. Makes no network request."""
    storage = open_storage()
    try:
        result = UpdateChecker.status(storage, UpdatesCommand.logger())
    finally:
        storage.close()
    UpdatesCommand.report(result, as_json)


@app.command("check")
def check(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Check for a newer policy now, ignoring the once-a-day limit, and show the result."""
    storage = open_storage()
    try:
        result = UpdateChecker.check(storage, force=True, logger=UpdatesCommand.logger())
    finally:
        storage.close()
    UpdatesCommand.report(result, as_json)


class UpdateNotice:
    """One line after a command's output when a newer version exists.

    Never prompts, never prints when output is piped or the check is off, and never fails or
    slows a command: it reads only the saved policy, with no network.
    """

    SKIPPED_COMMANDS = ("updates",)
    SKIPPED_FLAGS = ("--json", "--help", "-h", "--version")

    @staticmethod
    def is_terminal() -> bool:
        return bool(sys.stdout) and sys.stdout.isatty()

    @staticmethod
    def wanted(args: list[str]) -> bool:
        if not UpdateNotice.is_terminal():
            return False
        if args and args[0] in UpdateNotice.SKIPPED_COMMANDS:
            return False
        return not any(flag in args for flag in UpdateNotice.SKIPPED_FLAGS)

    @staticmethod
    def show(args: list[str]) -> None:
        try:
            if not UpdateNotice.wanted(args):
                return
            storage = open_storage()
            try:
                result = UpdateChecker.status(storage, UpdatesCommand.logger())
            finally:
                storage.close()
            if result.notify and result.message:
                console.print(
                    Text.assemble(
                        (result.message, Theme.NOTICE),
                        (" Details: ", "bright_black"),
                        ("vethuq updates status", Theme.COMMAND),
                    )
                )
        except Exception:  # noqa: BLE001 - a notice must never break a command
            UpdatesCommand.logger().debug("Update notice failed", exc_info=True)
