"""Processing and confidence statistics accumulated during OCR/indexing."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from vethuq_core.db import (
    clear_confidence_metrics,
    clear_processing_metrics,
    list_confidence_metrics,
    list_processing_metrics,
)


@dataclass(frozen=True)
class ProcessingMetric:
    file_type: str
    size_bucket: str
    document_count: int
    avg_duration_seconds: float
    avg_peak_memory_mb: float
    avg_cpu_percent: float
    updated_at: str
    phase: int = 1  # 1 = quick, 2 = moderate, 3 = deep


@dataclass(frozen=True)
class ConfidenceMetric:
    file_type: str
    process_type: str
    page_count: int
    avg_confidence: float
    updated_at: str


def get_processing_metrics(conn: sqlite3.Connection) -> list[ProcessingMetric]:
    """Return `processing_metrics`' per-(phase, file_type, size_bucket) running averages."""
    return [ProcessingMetric(**dict(row)) for row in list_processing_metrics(conn)]


def get_confidence_metrics(conn: sqlite3.Connection) -> list[ConfidenceMetric]:
    """Return `confidence_metrics`' per-(file_type, process_type) running averages."""
    return [ConfidenceMetric(**dict(row)) for row in list_confidence_metrics(conn)]


def reset_metrics(conn: sqlite3.Connection) -> None:
    """Clear `processing_metrics` and `confidence_metrics`.

    Both are running averages folded in per file/page as OCR completes, and
    `vethuq index run` reads `processing_metrics` for its ETA estimate -
    clearing them makes that estimate unavailable again until enough newly
    (re)indexed files have rebuilt the averages.
    """
    clear_processing_metrics(conn)
    clear_confidence_metrics(conn)
    conn.commit()
