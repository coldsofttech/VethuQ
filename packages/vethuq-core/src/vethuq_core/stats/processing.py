"""Processing statistics accumulated during OCR/indexing."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from vethuq_core.db.queries import Stats as StatsQuery


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


class Processing:
    @staticmethod
    def get_metrics(conn: sqlite3.Connection) -> list[ProcessingMetric]:
        """Return `processing_metrics`' per-(phase, file_type, size_bucket) running averages."""
        return [ProcessingMetric(**dict(row)) for row in StatsQuery.list_processing_metrics(conn)]

    @staticmethod
    def clear(conn: sqlite3.Connection) -> None:
        """Clear `processing_metrics` (without committing)."""
        StatsQuery.clear_processing_metrics(conn)
