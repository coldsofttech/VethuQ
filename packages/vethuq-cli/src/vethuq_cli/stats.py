"""`vethuq stats ...` commands for viewing/resetting OCR statistics."""

from __future__ import annotations

import os

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.db import connect
from vethuq_core.stats import (
    ConfidenceMetric,
    ProcessingMetric,
    get_confidence_metrics,
    get_processing_metrics,
    reset_metrics,
)

from vethuq_cli.console import console

app = typer.Typer(help="View and reset OCR processing/confidence statistics.")


def _processing_panel(metrics: list[ProcessingMetric]) -> Panel:
    if not metrics:
        body: Table | Text = Text("No processing statistics recorded yet.", style="bright_black")
    else:
        # `avg_cpu_percent` comes from psutil's per-process cpu_percent(), which
        # is normalized against a single core - dividing by the logical core
        # count turns it into the usual 0-100% "share of the whole machine"
        # reading, instead of e.g. 200%+ on a busy multi-core run.
        cpu_count = os.cpu_count() or 1
        body = Table(box=box.SIMPLE, header_style="bold cyan", border_style="cyan")
        body.add_column("File type")
        body.add_column("Documents", justify="right")
        body.add_column("Avg duration", justify="right")
        body.add_column("Avg peak memory", justify="right")
        body.add_column("Avg CPU", justify="right")
        for m in metrics:
            body.add_row(
                m.file_type,
                str(m.document_count),
                f"{m.avg_duration_seconds:.1f}s",
                f"{m.avg_peak_memory_mb:.0f} MB",
                f"{m.avg_cpu_percent / cpu_count:.0f}%",
            )
    return Panel(body, title="Processing", border_style="cyan")


def _confidence_panel(metrics: list[ConfidenceMetric]) -> Panel:
    if not metrics:
        body: Table | Text = Text("No confidence statistics recorded yet.", style="bright_black")
    else:
        body = Table(box=box.SIMPLE, header_style="bold magenta", border_style="magenta")
        body.add_column("File type")
        body.add_column("Process type")
        body.add_column("Pages", justify="right")
        body.add_column("Avg confidence", justify="right")
        for m in metrics:
            body.add_row(m.file_type, m.process_type, str(m.page_count), f"{m.avg_confidence:.0%}")
    return Panel(body, title="Confidence", border_style="magenta")


def _align_widths(render_console: Console, *panels: Panel) -> None:
    """Give every panel the widest one's width, so a `show` with both panels
    printed one after another reads as a single, aligned block instead of
    each panel hugging its own content.
    """
    width = max(render_console.measure(panel).maximum for panel in panels)
    for panel in panels:
        panel.width = width


@app.command("show")
def show() -> None:
    """Show accumulated OCR processing and confidence statistics."""
    conn = connect()
    try:
        processing = get_processing_metrics(conn)
        confidence = get_confidence_metrics(conn)
    finally:
        conn.close()
    processing_panel = _processing_panel(processing)
    confidence_panel = _confidence_panel(confidence)
    _align_widths(console, processing_panel, confidence_panel)
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

    conn = connect()
    try:
        reset_metrics(conn)
    finally:
        conn.close()
    console.print("Statistics reset.", style="bold green")
