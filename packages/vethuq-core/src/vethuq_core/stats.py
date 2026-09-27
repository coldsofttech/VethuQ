"""Processing and confidence statistics accumulated during OCR/indexing."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessingMetric:
    file_type: str
    size_bucket: str
    document_count: int
    avg_duration_seconds: float
    avg_peak_memory_mb: float
    avg_cpu_percent: float
    updated_at: str


@dataclass(frozen=True)
class ConfidenceMetric:
    file_type: str
    process_type: str
    page_count: int
    avg_confidence: float
    updated_at: str


def get_processing_metrics(conn: sqlite3.Connection) -> list[ProcessingMetric]:
    """Return `processing_metrics`' per-(file_type, size_bucket) running averages."""
    rows = conn.execute(
        "SELECT file_type, size_bucket, document_count, avg_duration_seconds, "
        "avg_peak_memory_mb, avg_cpu_percent, updated_at FROM processing_metrics "
        "ORDER BY file_type, size_bucket"
    ).fetchall()
    return [ProcessingMetric(**dict(row)) for row in rows]


def get_confidence_metrics(conn: sqlite3.Connection) -> list[ConfidenceMetric]:
    """Return `confidence_metrics`' per-(file_type, process_type) running averages."""
    rows = conn.execute(
        "SELECT file_type, process_type, page_count, avg_confidence, updated_at "
        "FROM confidence_metrics ORDER BY file_type, process_type"
    ).fetchall()
    return [ConfidenceMetric(**dict(row)) for row in rows]


def reset_metrics(conn: sqlite3.Connection) -> None:
    """Clear `processing_metrics` and `confidence_metrics`.

    Both are running averages folded in per file/page as OCR completes, and
    `vethuq index run` reads `processing_metrics` for its ETA estimate -
    clearing them makes that estimate unavailable again until enough newly
    (re)indexed files have rebuilt the averages.
    """
    conn.execute("DELETE FROM processing_metrics")
    conn.execute("DELETE FROM confidence_metrics")
    conn.commit()
