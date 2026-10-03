"""Processing statistics accumulated during OCR/indexing."""

from __future__ import annotations

import os
from dataclasses import dataclass

from vethuq_core.storage import Storage


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

    @property
    def avg_machine_cpu_percent(self) -> float:
        """`avg_cpu_percent` as a share of the whole machine (0-100%).

        `avg_cpu_percent` comes from psutil's per-process cpu_percent(), which is
        normalized against a single core - dividing by the logical core count
        turns it into the usual "share of the whole machine" reading, instead of
        e.g. 200%+ on a busy multi-core run.
        """
        return self.avg_cpu_percent / (os.cpu_count() or 1)


class Processing:
    @staticmethod
    def get_metrics(storage: Storage) -> list[ProcessingMetric]:
        """Return `processing_metrics`' per-(phase, file_type, size_bucket) running averages."""
        return [ProcessingMetric(**dict(row)) for row in storage.list_processing_metrics()]

    @staticmethod
    def clear(storage: Storage) -> None:
        """Clear `processing_metrics` (without committing)."""
        storage.clear_processing_metrics()
