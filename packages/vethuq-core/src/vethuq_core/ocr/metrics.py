"""Folding per-document measurements into the running processing/confidence averages."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from vethuq_core.db.queries import Document as DocumentQuery
from vethuq_core.db.queries import Stats as StatsQuery

_logger = logging.getLogger(__name__)


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
    def update_processing(conn: sqlite3.Connection, document_id: int, file_type: str) -> None:
        """Fold one freshly-indexed document's quick-pass (phase 1) duration/memory/cpu into
        `processing_metrics`'s running averages.

        Called only for successfully indexed documents - a failed document has a
        duration that doesn't reflect a full OCR pass, so it would skew the
        averages `vethuq index run` uses to estimate ETAs.
        """
        doc = DocumentQuery.get_index_metrics_stats(conn, document_id)
        duration = (
            datetime.fromisoformat(doc["completed_at"]) - datetime.fromisoformat(doc["started_at"])
        ).total_seconds()
        Metrics.fold_processing(
            conn,
            phase=1,
            file_type=file_type,
            file_size_bytes=doc["file_size_bytes"] or 0,
            duration=duration,
            peak_memory_mb=doc["peak_memory_mb"] or 0.0,
            cpu_percent=doc["cpu_percent"] or 0.0,
        )

    @staticmethod
    def fold_processing(
        conn: sqlite3.Connection,
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
        existing = StatsQuery.get_processing_metrics_row(conn, phase, file_type, size_bucket)
        if existing is None:
            StatsQuery.insert_processing_metrics(
                conn, phase, file_type, size_bucket, duration, peak_memory_mb, cpu_percent, now
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
        StatsQuery.update_processing_metrics(
            conn,
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
    def update_confidence(conn: sqlite3.Connection, document_id: int, file_type: str) -> None:
        """Fold one freshly-indexed document's pages into `confidence_metrics`'s running
        averages, grouped independently by (file_type, process_type).

        Native pages run near-100% confidence while OCR/mixed pages don't, so
        blending them into a single average would dilute the OCR/mixed signal -
        tracking each process_type separately keeps them meaningful.
        """
        if file_type == "pdf":
            pages = DocumentQuery.get_pdf_page_sources(conn, document_id)
        else:
            pages = DocumentQuery.get_page_confidences(conn, file_type, document_id)
        if not pages:
            return

        by_process_type: dict[str, list[float]] = {}
        for page in pages:
            process_type = (
                page["source"] if file_type == "pdf" else "native" if file_type == "eml" else "ocr"
            )
            by_process_type.setdefault(process_type, []).append(page["confidence"])

        now = datetime.now(UTC).isoformat()
        for process_type, confidences in by_process_type.items():
            existing = StatsQuery.get_confidence_metrics_row(conn, file_type, process_type)
            if existing is None:
                StatsQuery.insert_confidence_metrics(
                    conn,
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
            StatsQuery.update_confidence_metrics(
                conn, file_type, process_type, new_count, avg_confidence, now
            )
