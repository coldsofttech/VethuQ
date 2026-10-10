"""`vethuq policy ...` commands: what the signed policy says and a way to refresh it."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.logs import Logs
from vethuq_core.policy import PolicyResult, PolicyService, PolicySource, PolicyStatus

from vethuq_cli.console import console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Show the signed policy VethuQ follows, or check for a newer one.")


class PolicyCommand:
    TITLE = "Policy"

    SOURCES = {
        PolicySource.FETCHED: "fetched just now",
        PolicySource.CACHE: "saved from an earlier check",
        PolicySource.BASELINE: "built-in baseline (no signed policy yet)",
    }

    @staticmethod
    def rows(result: PolicyResult) -> list[tuple[str, str]]:
        policy = result.policy
        rows = [
            ("Source", PolicyCommand.SOURCES[result.source]),
            ("Sequence", str(policy.sequence)),
            ("Issued", policy.issued_at.strftime("%Y-%m-%d %H:%M UTC")),
            ("Signed by", policy.kid),
        ]
        for name, versions in policy.versions.items():
            rows.append(
                (
                    f"{name} version",
                    f"latest {versions.latest}, minimum {versions.minimum_supported}",
                )
            )
        for notice in policy.active_notices():
            rows.append((f"Notice ({notice.severity})", notice.message))
        if result.update_required:
            rows.append(("Update", PolicyResult.UPDATE_MESSAGE))
        return rows

    @staticmethod
    def panel(result: PolicyResult, note: str | None = None) -> Panel:
        table = Table.grid(padding=(0, 2))
        for label, value in PolicyCommand.rows(result):
            table.add_row(Text(label, style="bold"), Text(value))
        if note:
            table.add_row(Text("Check", style="bold"), Text(note))
        return Panel(
            table,
            title=Text(PolicyCommand.TITLE),
            title_align="left",
            border_style=Theme.PRIMARY,
            expand=True,
        )

    @staticmethod
    def describe(result: PolicyResult) -> str:
        """One line on how a check went."""
        messages = {
            PolicyStatus.UPDATED: "a newer policy was accepted",
            PolicyStatus.UNCHANGED: "nothing newer",
            PolicyStatus.SKIPPED: "skipped",
            PolicyStatus.OFFLINE: "could not reach the policy servers; keeping the saved policy",
            PolicyStatus.REJECTED: "the policy was refused; keeping the saved policy",
            PolicyStatus.UPDATE_REQUIRED: PolicyResult.UPDATE_MESSAGE,
            PolicyStatus.CURRENT: "",
        }
        message = messages[result.status]
        return f"{message} ({result.detail})" if result.detail and message else message

    @staticmethod
    def logger():  # noqa: ANN205 - a stdlib logger
        return Logs.get_logger("cli")


@app.command("show")
def show() -> None:
    """Show the policy in use (saved or built-in). Makes no network request."""
    console.print(PolicyCommand.panel(PolicyService.current(PolicyCommand.logger())))


@app.command("refresh")
def refresh() -> None:
    """Check for a newer policy now, ignoring the once-a-day limit."""
    result = PolicyService.client(PolicyCommand.logger()).refresh(force=True)
    console.print(PolicyCommand.panel(result, PolicyCommand.describe(result)))
