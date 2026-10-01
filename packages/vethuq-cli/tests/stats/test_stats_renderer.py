import io
import os

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from vethuq_cli.stats.renderer import StatsRenderer
from vethuq_core.stats import ProcessingMetric


class TestStatsRenderer:
    def test_processing_panel_normalizes_cpu_percent_by_core_count(self, monkeypatch):
        monkeypatch.setattr(os, "cpu_count", lambda: 4)
        metric = ProcessingMetric(
            file_type="pdf",
            size_bucket="medium",
            document_count=1,
            avg_duration_seconds=1.0,
            avg_peak_memory_mb=1.0,
            avg_cpu_percent=200.0,
            updated_at="2026-01-01T00:00:00+00:00",
        )

        panel = StatsRenderer.processing_panel([metric])
        buffer = io.StringIO()
        Console(file=buffer, width=120).print(panel)

        assert "50%" in buffer.getvalue()

    def test_align_widths_matches_the_widest_panel(self):
        narrow = Panel(Text("x"), title="A")
        wide = Panel(Text("x" * 50), title="B")
        console = Console(file=io.StringIO(), width=120)

        StatsRenderer.align_widths(console, narrow, wide)

        assert narrow.width == wide.width
