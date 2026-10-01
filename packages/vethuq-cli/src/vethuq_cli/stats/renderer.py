"""Rich panels for the processing/confidence statistics."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.ocr import Deepening
from vethuq_core.stats import ConfidenceMetric, ProcessingMetric

from vethuq_cli.theme import Theme


class StatsRenderer:
    @staticmethod
    def processing_panel(metrics: list[ProcessingMetric]) -> Panel:
        if not metrics:
            body: Table | Text = Text(
                "No processing statistics recorded yet.", style="bright_black"
            )
        else:
            body = Table(
                box=box.SIMPLE, header_style=f"bold {Theme.PRIMARY}", border_style=Theme.PRIMARY
            )
            body.add_column("Phase")
            body.add_column("File type")
            body.add_column("Size")
            body.add_column("Documents", justify="right")
            body.add_column("Avg duration", justify="right")
            body.add_column("Avg peak memory", justify="right")
            body.add_column("Avg CPU", justify="right")
            for m in metrics:
                body.add_row(
                    Deepening.PHASE_NAMES.get(m.phase, str(m.phase)),
                    m.file_type,
                    m.size_bucket,
                    str(m.document_count),
                    f"{m.avg_duration_seconds:.1f}s",
                    f"{m.avg_peak_memory_mb:.0f} MB",
                    f"{m.avg_machine_cpu_percent:.0f}%",
                )
        return Panel(body, title="Processing", border_style=Theme.PRIMARY)

    @staticmethod
    def confidence_panel(metrics: list[ConfidenceMetric]) -> Panel:
        if not metrics:
            body: Table | Text = Text(
                "No confidence statistics recorded yet.", style="bright_black"
            )
        else:
            body = Table(
                box=box.SIMPLE, header_style=f"bold {Theme.ACCENT}", border_style=Theme.ACCENT
            )
            body.add_column("File type")
            body.add_column("Process type")
            body.add_column("Pages", justify="right")
            body.add_column("Avg confidence", justify="right")
            for m in metrics:
                body.add_row(
                    m.file_type, m.process_type, str(m.page_count), f"{m.avg_confidence:.0%}"
                )
        return Panel(body, title="Confidence", border_style=Theme.ACCENT)

    @staticmethod
    def align_widths(render_console: Console, *panels: Panel) -> None:
        """Give every panel the widest one's width, so a `show` with both panels
        printed one after another reads as a single, aligned block instead of
        each panel hugging its own content.
        """
        width = max(render_console.measure(panel).maximum for panel in panels)
        for panel in panels:
            panel.width = width
