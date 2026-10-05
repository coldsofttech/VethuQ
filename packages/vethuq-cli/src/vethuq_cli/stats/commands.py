"""`vethuq stats ...` commands for viewing/resetting OCR statistics."""

from __future__ import annotations

import typer
from rich.prompt import Confirm
from vethuq_core.languages import Languages
from vethuq_core.stats import Confidence, Processing, Stats
from vethuq_core.storage import open_storage

from vethuq_cli.console import console
from vethuq_cli.stats.renderer import StatsRenderer
from vethuq_cli.theme import Theme

app = typer.Typer(help="View and reset OCR processing/confidence statistics.")


@app.command("show")
def show(
    lang: str | None = typer.Option(
        None,
        "--lang",
        help="Only this OCR language's statistics ('en', 'te'). Default: every language.",
    ),
) -> None:
    """Show accumulated OCR processing and confidence statistics.

    Each language keeps its own averages (Telugu pages are slower to read and score lower than
    English ones), shown in a Language column once more than one language has statistics.
    """
    if lang is not None and Languages.get(lang.strip().lower()) is None:
        raise typer.BadParameter(f"Unknown language '{lang}'.", param_hint="--lang")
    storage = open_storage()
    try:
        processing = Processing.get_metrics(storage, lang.strip().lower() if lang else None)
        confidence = Confidence.get_metrics(storage, lang.strip().lower() if lang else None)
    finally:
        storage.close()
    processing_panel = StatsRenderer.processing_panel(processing)
    confidence_panel = StatsRenderer.confidence_panel(confidence)
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
        console.print(StatsRenderer.reset_panel("Aborted.", "bright_black"))
        raise typer.Exit(code=0)

    storage = open_storage()
    try:
        Stats.reset(storage)
    finally:
        storage.close()
    console.print(StatsRenderer.reset_panel("Statistics reset.", Theme.OK))
