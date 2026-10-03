"""Confidence statistics accumulated during OCR/indexing."""

from __future__ import annotations

from dataclasses import dataclass

from vethuq_core.storage import Storage


@dataclass(frozen=True)
class ConfidenceMetric:
    file_type: str
    process_type: str
    page_count: int
    avg_confidence: float
    updated_at: str


class Confidence:
    @staticmethod
    def get_metrics(storage: Storage) -> list[ConfidenceMetric]:
        """Return `confidence_metrics`' per-(file_type, process_type) running averages."""
        return [ConfidenceMetric(**dict(row)) for row in storage.list_confidence_metrics()]

    @staticmethod
    def clear(storage: Storage) -> None:
        """Clear `confidence_metrics` (without committing)."""
        storage.clear_confidence_metrics()
