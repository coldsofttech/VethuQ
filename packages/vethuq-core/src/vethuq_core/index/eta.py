"""Estimating how long an index run has left, from each phase's own history."""

from __future__ import annotations

import sqlite3

from vethuq_core.db.queries import Stats as StatsQuery
from vethuq_core.index.runner import IndexRunner, IndexState
from vethuq_core.ocr import Deepening, Pending, Readers
from vethuq_core.source import SourceNotFoundError


class Eta:
    @staticmethod
    def average_durations(conn: sqlite3.Connection, phase: int) -> dict[str, float]:
        """Average document duration per file_type for `phase`, across all past runs.

        `processing_metrics` has one row per (phase, file_type, size_bucket) - each
        bucket's average is weighted by its document_count so a file_type with an
        uneven mix of small/large files still gets one sensible average back.
        """
        return {
            row["file_type"]: row["avg_duration_seconds"]
            for row in StatsQuery.get_processing_metrics_avg_duration_by_file_type(conn, phase)
        }

    @staticmethod
    def phase_seconds(conn: sqlite3.Connection, state: IndexState) -> dict[int, float]:
        """Estimate the seconds left in each OCR phase, from that phase's own history.

        Each phase is sized by the documents it still has to cover, split by
        file_type (pdf/image - OCR at very different speeds), and multiplied by
        that type's average duration *for that phase* across all past runs,
        rather than this run's own pace, which is noisy - or unavailable - early
        in a run. A quick pass's timings say nothing about a deep one, so a phase
        with no history yet simply has no estimate. Only phases the `index_engine`
        setting reaches, and that still have work, appear in the result.
        """
        try:
            sources = IndexRunner.resolve_targets(conn, state.target)
        except SourceNotFoundError:
            return {}

        quick_remaining = Readers.new_file_type_counts()
        for source in sources:
            counts = Pending.file_type_counts(
                conn,
                source,
                only_new_files=source.status != "pending",
                only_failed=state.mode == "restart",
            )
            for file_type, count in counts.items():
                quick_remaining[file_type] += count

        remaining_by_phase = {1: quick_remaining}
        for phase in range(2, Deepening.max_phase(conn) + 1):
            remaining_by_phase[phase] = Deepening.pending_documents(conn, sources, phase)

        seconds_by_phase: dict[int, float] = {}
        for phase, remaining in remaining_by_phase.items():
            if not any(remaining.values()):
                continue
            averages = Eta.average_durations(conn, phase)
            seconds_left = sum(
                count * averages[file_type]
                for file_type, count in remaining.items()
                if count > 0 and file_type in averages
            )
            if seconds_left > 0:
                seconds_by_phase[phase] = seconds_left
        return seconds_by_phase

    @staticmethod
    def total_seconds(conn: sqlite3.Connection, state: IndexState) -> float:
        """Total time left across every phase still to run (0 if it can't be estimated)."""
        return sum(Eta.phase_seconds(conn, state).values())
