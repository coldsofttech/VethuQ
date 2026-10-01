"""Confidence statistics accumulated during OCR/indexing."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from vethuq_core.db.queries import Stats as StatsQuery


@dataclass(frozen=True)
class ConfidenceMetric:
    file_type: str
    process_type: str
    page_count: int
    avg_confidence: float
    updated_at: str


class Confidence:
    @staticmethod
    def get_metrics(conn: sqlite3.Connection) -> list[ConfidenceMetric]:
        """Return `confidence_metrics`' per-(file_type, process_type) running averages."""
        return [ConfidenceMetric(**dict(row)) for row in StatsQuery.list_confidence_metrics(conn)]

    @staticmethod
    def clear(conn: sqlite3.Connection) -> None:
        """Clear `confidence_metrics` (without committing)."""
        StatsQuery.clear_confidence_metrics(conn)
