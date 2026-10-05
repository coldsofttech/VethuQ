"""SQL for the `processing_metrics` and `confidence_metrics` tables.

Both are keyed by OCR language as well (`language`), so each language keeps its own averages.
"""

from __future__ import annotations

import sqlite3


class Stats:
    @staticmethod
    def get_processing_metrics_row(
        conn: sqlite3.Connection, phase: int, extension: str, size_bucket: str, language: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT document_count, avg_duration_seconds, "
            "avg_peak_memory_mb, avg_cpu_percent FROM processing_metrics "
            "WHERE phase = ? AND extension = ? AND size_bucket = ? AND language = ?",
            (phase, extension, size_bucket, language),
        ).fetchone()

    @staticmethod
    def get_processing_metrics_budget_row(
        conn: sqlite3.Connection, phase: int, extension: str, size_bucket: str
    ) -> sqlite3.Row | None:
        """The memory/cpu footprint of a file like this, averaged over every language: whichever
        language the file turns out to be in, the scheduler must not start it on a busy machine."""
        row = conn.execute(
            "SELECT SUM(avg_peak_memory_mb * document_count) / SUM(document_count) "
            "AS avg_peak_memory_mb, "
            "SUM(avg_cpu_percent * document_count) / SUM(document_count) AS avg_cpu_percent "
            "FROM processing_metrics "
            "WHERE phase = ? AND extension = ? AND size_bucket = ? AND document_count > 0",
            (phase, extension, size_bucket),
        ).fetchone()
        return None if row is None or row["avg_peak_memory_mb"] is None else row

    @staticmethod
    def insert_processing_metrics(
        conn: sqlite3.Connection,
        phase: int,
        file_type: str,
        extension: str,
        size_bucket: str,
        duration: float,
        peak_memory_mb: float,
        cpu_percent: float,
        updated_at: str,
        language: str,
    ) -> None:
        conn.execute(
            "INSERT INTO processing_metrics "
            "(phase, file_type, extension, size_bucket, document_count, avg_duration_seconds, "
            "avg_peak_memory_mb, avg_cpu_percent, updated_at, language) "
            "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
            (
                phase,
                file_type,
                extension,
                size_bucket,
                duration,
                peak_memory_mb,
                cpu_percent,
                updated_at,
                language,
            ),
        )

    @staticmethod
    def update_processing_metrics(
        conn: sqlite3.Connection,
        phase: int,
        extension: str,
        size_bucket: str,
        document_count: int,
        avg_duration_seconds: float,
        avg_peak_memory_mb: float,
        avg_cpu_percent: float,
        updated_at: str,
        language: str,
    ) -> None:
        conn.execute(
            "UPDATE processing_metrics SET document_count = ?, avg_duration_seconds = ?, "
            "avg_peak_memory_mb = ?, avg_cpu_percent = ?, updated_at = ? "
            "WHERE phase = ? AND extension = ? AND size_bucket = ? AND language = ?",
            (
                document_count,
                avg_duration_seconds,
                avg_peak_memory_mb,
                avg_cpu_percent,
                updated_at,
                phase,
                extension,
                size_bucket,
                language,
            ),
        )

    @staticmethod
    def get_confidence_metrics_row(
        conn: sqlite3.Connection, extension: str, process_type: str, language: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT page_count, avg_confidence FROM confidence_metrics "
            "WHERE extension = ? AND process_type = ? AND language = ?",
            (extension, process_type, language),
        ).fetchone()

    @staticmethod
    def insert_confidence_metrics(
        conn: sqlite3.Connection,
        file_type: str,
        extension: str,
        process_type: str,
        page_count: int,
        avg_confidence: float,
        updated_at: str,
        language: str,
    ) -> None:
        conn.execute(
            "INSERT INTO confidence_metrics "
            "(file_type, extension, process_type, page_count, avg_confidence, updated_at, "
            "language) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_type, extension, process_type, page_count, avg_confidence, updated_at, language),
        )

    @staticmethod
    def update_confidence_metrics(
        conn: sqlite3.Connection,
        extension: str,
        process_type: str,
        page_count: int,
        avg_confidence: float,
        updated_at: str,
        language: str,
    ) -> None:
        conn.execute(
            "UPDATE confidence_metrics SET page_count = ?, avg_confidence = ?, updated_at = ? "
            "WHERE extension = ? AND process_type = ? AND language = ?",
            (page_count, avg_confidence, updated_at, extension, process_type, language),
        )

    @staticmethod
    def list_processing_metrics(
        conn: sqlite3.Connection, language: str | None = None
    ) -> list[sqlite3.Row]:
        where, args = ("WHERE language = ? ", (language,)) if language else ("", ())
        return conn.execute(
            "SELECT phase, language, file_type, extension, size_bucket, document_count, "
            "avg_duration_seconds, avg_peak_memory_mb, avg_cpu_percent, updated_at "
            f"FROM processing_metrics {where}ORDER BY language, phase, extension, size_bucket",
            args,
        ).fetchall()

    @staticmethod
    def list_confidence_metrics(
        conn: sqlite3.Connection, language: str | None = None
    ) -> list[sqlite3.Row]:
        where, args = ("WHERE language = ? ", (language,)) if language else ("", ())
        return conn.execute(
            "SELECT language, file_type, extension, process_type, page_count, avg_confidence, "
            f"updated_at FROM confidence_metrics {where}ORDER BY language, extension, process_type",
            args,
        ).fetchall()

    @staticmethod
    def clear_processing_metrics(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM processing_metrics")

    @staticmethod
    def clear_confidence_metrics(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM confidence_metrics")

    @staticmethod
    def get_processing_metrics_avg_duration_by_file_type(
        conn: sqlite3.Connection, phase: int
    ) -> list[sqlite3.Row]:
        """Per-file_type average duration for `phase`, weighted by each row's document_count
        (so size buckets and languages count in proportion to the documents behind them)."""
        return conn.execute(
            "SELECT file_type, "
            "SUM(avg_duration_seconds * document_count) / SUM(document_count) "
            "AS avg_duration_seconds "
            "FROM processing_metrics WHERE phase = ? AND document_count > 0 GROUP BY file_type",
            (phase,),
        ).fetchall()
