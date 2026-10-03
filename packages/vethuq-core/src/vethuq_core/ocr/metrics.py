"""Folding per-document measurements into the running processing/confidence averages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from vethuq_core.logs import Logs
from vethuq_core.readers import Readers
from vethuq_core.storage import Storage

_logger = Logs.get_logger("index")


class Metrics:
    # Keep these in sync with the literal byte thresholds in db.py's version-16
    # migration, which buckets historical document_index rows the same way.
    SIZE_BUCKET_SMALL_MAX_BYTES = 500_000
    SIZE_BUCKET_MEDIUM_MAX_BYTES = 3_000_000

    @staticmethod
    def size_bucket(file_size_bytes: int) -> str:
        """Classify a file's size into the coarse bucket `processing_metrics` is keyed by."""
        if file_size_bytes < Metrics.SIZE_BUCKET_SMALL_MAX_BYTES:
            return "small"
        if file_size_bytes < Metrics.SIZE_BUCKET_MEDIUM_MAX_BYTES:
            return "medium"
        return "large"

    @staticmethod
    def update_processing(storage: Storage, document_id: int, file_type: str) -> None:
        """Fold one freshly-indexed document's quick-pass (phase 1) duration/memory/cpu into
        `processing_metrics`'s running averages.

        Called only for successfully indexed documents - a failed document has a
        duration that doesn't reflect a full OCR pass, so it would skew the
        averages `vethuq index run` uses to estimate ETAs.
        """
        doc = storage.get_document_index_metrics_stats(document_id)
        duration = (
            datetime.fromisoformat(doc["completed_at"]) - datetime.fromisoformat(doc["started_at"])
        ).total_seconds()
        Metrics.fold_processing(
            storage,
            phase=1,
            file_type=file_type,
            file_size_bytes=doc["file_size_bytes"] or 0,
            duration=duration,
            peak_memory_mb=doc["peak_memory_mb"] or 0.0,
            cpu_percent=doc["cpu_percent"] or 0.0,
        )

    @staticmethod
    def fold_processing(
        storage: Storage,
        *,
        phase: int,
        file_type: str,
        file_size_bytes: int,
        duration: float,
        peak_memory_mb: float,
        cpu_percent: float,
    ) -> None:
        """Fold one document's measurements for `phase` into that phase's running averages.

        Each phase keeps its own averages - a deep pass takes many times longer
        than a quick one, so blending them would make every ETA wrong.
        """
        size_bucket = Metrics.size_bucket(file_size_bytes)
        now = datetime.now(UTC).isoformat()
        existing = storage.get_processing_metrics_row(phase, file_type, size_bucket)
        if existing is None:
            storage.insert_processing_metrics(
                phase, file_type, size_bucket, duration, peak_memory_mb, cpu_percent, now
            )
            return
        new_count = existing["document_count"] + 1
        avg_duration = (
            existing["avg_duration_seconds"]
            + (duration - existing["avg_duration_seconds"]) / new_count
        )
        avg_peak_memory_mb = (
            existing["avg_peak_memory_mb"]
            + (peak_memory_mb - existing["avg_peak_memory_mb"]) / new_count
        )
        avg_cpu_percent = (
            existing["avg_cpu_percent"] + (cpu_percent - existing["avg_cpu_percent"]) / new_count
        )
        storage.update_processing_metrics(
            phase,
            file_type,
            size_bucket,
            new_count,
            avg_duration,
            avg_peak_memory_mb,
            avg_cpu_percent,
            now,
        )

    @staticmethod
    def update_confidence(storage: Storage, document_id: int, file_type: str) -> None:
        """Fold one freshly-indexed document's pages into `confidence_metrics`'s running
        averages, grouped independently by (file_type, process_type).

        Native pages run near-100% confidence while OCR/mixed pages don't, so
        blending them into a single average would dilute the OCR/mixed signal -
        tracking each process_type separately keeps them meaningful.
        """
        by_process_type = Readers.for_file_type(file_type).storage.confidences_by_process_type(
            storage, document_id
        )
        if not by_process_type:
            return

        now = datetime.now(UTC).isoformat()
        for process_type, confidences in by_process_type.items():
            existing = storage.get_confidence_metrics_row(file_type, process_type)
            if existing is None:
                storage.insert_confidence_metrics(
                    file_type,
                    process_type,
                    len(confidences),
                    sum(confidences) / len(confidences),
                    now,
                )
                continue

            new_count = existing["page_count"] + len(confidences)
            avg_confidence = (
                existing["avg_confidence"] * existing["page_count"] + sum(confidences)
            ) / new_count
            storage.update_confidence_metrics(
                file_type, process_type, new_count, avg_confidence, now
            )
