"""`vethuq stats ...` commands for viewing/resetting OCR statistics."""

from __future__ import annotations

import typer
from rich.prompt import Confirm
from vethuq_core.db import Db
from vethuq_core.stats import Confidence, Processing, Stats

from vethuq_cli.console import console
from vethuq_cli.stats.renderer import StatsRenderer
from vethuq_cli.theme import Theme

app = typer.Typer(help="View and reset OCR processing/confidence statistics.")


@app.command("show")
def show() -> None:
    """Show accumulated OCR processing and confidence statistics."""
    conn = Db.connect()
    try:
        processing = Processing.get_metrics(conn)
        confidence = Confidence.get_metrics(conn)
    finally:
        conn.close()
    processing_panel = StatsRenderer.processing_panel(processing)
    confidence_panel = StatsRenderer.confidence_panel(confidence)
    StatsRenderer.align_widths(console, processing_panel, confidence_panel)
    console.print(processing_panel)
    console.print(confidence_panel)


@app.command("reset")
def reset(
    force: bool = typer.Option(False, "--force", help="Reset without asking for confirmation."),
) -> None:
    """Clear processing and confidence statistics.

    These are running averages folded in as OCR completes, and
    `vethuq index run`'s ETA estimate is based on them - after a reset, ETAs
    are unavailable again until enough files have been (re)indexed to
    rebuild them.
    """
    if not force and not Confirm.ask(
        "Reset processing and confidence statistics? ETA estimates for "
        "upcoming index runs will be unavailable until enough files have "
        "been indexed again to rebuild them.",
        console=console,
        default=False,
    ):
        console.print("Aborted.", style="bright_black")
        raise typer.Exit(code=0)

    conn = Db.connect()
    try:
        Stats.reset(conn)
    finally:
        conn.close()
    console.print("Statistics reset.", style=Theme.OK)
