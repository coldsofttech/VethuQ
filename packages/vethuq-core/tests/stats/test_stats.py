import os
import sqlite3
from datetime import UTC, datetime

import pytest
from vethuq_core.stats import Confidence, Processing, ProcessingMetric, Stats


def _seed_metrics(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO processing_metrics "
        "(file_type, size_bucket, document_count, avg_duration_seconds, avg_peak_memory_mb, "
        "avg_cpu_percent, updated_at) VALUES ('pdf', 'medium', 2, 5.0, 100.0, 10.0, ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO confidence_metrics "
        "(file_type, process_type, page_count, avg_confidence, updated_at) "
        "VALUES ('pdf', 'native', 3, 1.0, ?)",
        (now,),
    )
    conn.commit()


class TestProcessing:
    def test_avg_machine_cpu_percent_divides_by_core_count(self, monkeypatch):
        monkeypatch.setattr(os, "cpu_count", lambda: 4)
        metric = ProcessingMetric("pdf", "medium", 2, 5.0, 100.0, 200.0, "now")

        assert metric.avg_machine_cpu_percent == pytest.approx(50.0)

    def test_get_processing_metrics_returns_rows(self, conn: sqlite3.Connection):
        _seed_metrics(conn)

        metrics = Processing.get_metrics(conn)

        assert len(metrics) == 1
        assert metrics[0].file_type == "pdf"
        assert metrics[0].document_count == 2
        assert metrics[0].avg_duration_seconds == pytest.approx(5.0)


class TestConfidence:
    def test_get_confidence_metrics_returns_rows(self, conn: sqlite3.Connection):
        _seed_metrics(conn)

        metrics = Confidence.get_metrics(conn)

        assert len(metrics) == 1
        assert metrics[0].file_type == "pdf"
        assert metrics[0].process_type == "native"
        assert metrics[0].page_count == 3
        assert metrics[0].avg_confidence == pytest.approx(1.0)


class TestStats:
    def test_get_metrics_empty_when_no_data(self, conn: sqlite3.Connection):
        assert Processing.get_metrics(conn) == []
        assert Confidence.get_metrics(conn) == []

    def test_reset_metrics_clears_both_tables(self, conn: sqlite3.Connection):
        _seed_metrics(conn)

        Stats.reset(conn)

        assert Processing.get_metrics(conn) == []
        assert Confidence.get_metrics(conn) == []
