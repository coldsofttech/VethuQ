"""Confidence statistics accumulated during OCR/indexing."""

from __future__ import annotations

from dataclasses import dataclass

from vethuq_core.storage import Storage


@dataclass(frozen=True)
class ConfidenceMetric:
    file_type: str  # 'pdf' | 'image': how the file's pages are stored
    extension: str  # 'pdf', 'png', 'jpg', ...: what the averages are tracked per
    process_type: str
    page_count: int
    avg_confidence: float
    updated_at: str
    language: str = "en"  # the OCR language the averages are for


class Confidence:
    @staticmethod
    def get_metrics(storage: Storage, language: str | None = None) -> list[ConfidenceMetric]:
        """Return `confidence_metrics`' per-(language, extension, process_type) running averages;
        `language` limits them to one language."""
        return [ConfidenceMetric(**dict(row)) for row in storage.list_confidence_metrics(language)]

    @staticmethod
    def clear(storage: Storage) -> None:
        """Clear `confidence_metrics` (without committing)."""
        storage.clear_confidence_metrics()
