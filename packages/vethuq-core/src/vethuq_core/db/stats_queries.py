"""SQL for the `processing_metrics` and `confidence_metrics` tables."""

from __future__ import annotations

import sqlite3


def get_processing_metrics_row(
    conn: sqlite3.Connection, file_type: str, size_bucket: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT document_count, avg_duration_seconds, "
        "avg_peak_memory_mb, avg_cpu_percent FROM processing_metrics "
        "WHERE file_type = ? AND size_bucket = ?",
        (file_type, size_bucket),
    ).fetchone()


def get_processing_metrics_budget_row(
    conn: sqlite3.Connection, file_type: str, size_bucket: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT avg_peak_memory_mb, avg_cpu_percent FROM processing_metrics "
        "WHERE file_type = ? AND size_bucket = ?",
        (file_type, size_bucket),
    ).fetchone()


def insert_processing_metrics(
    conn: sqlite3.Connection,
    file_type: str,
    size_bucket: str,
    duration: float,
    peak_memory_mb: float,
    cpu_percent: float,
    updated_at: str,
) -> None:
    conn.execute(
        "INSERT INTO processing_metrics "
        "(file_type, size_bucket, document_count, avg_duration_seconds, avg_peak_memory_mb, "
        "avg_cpu_percent, updated_at) "
        "VALUES (?, ?, 1, ?, ?, ?, ?)",
        (file_type, size_bucket, duration, peak_memory_mb, cpu_percent, updated_at),
    )


def update_processing_metrics(
    conn: sqlite3.Connection,
    file_type: str,
    size_bucket: str,
    document_count: int,
    avg_duration_seconds: float,
    avg_peak_memory_mb: float,
    avg_cpu_percent: float,
    updated_at: str,
) -> None:
    conn.execute(
        "UPDATE processing_metrics SET document_count = ?, avg_duration_seconds = ?, "
        "avg_peak_memory_mb = ?, avg_cpu_percent = ?, updated_at = ? "
        "WHERE file_type = ? AND size_bucket = ?",
        (
            document_count,
            avg_duration_seconds,
            avg_peak_memory_mb,
            avg_cpu_percent,
            updated_at,
            file_type,
            size_bucket,
        ),
    )


def get_confidence_metrics_row(
    conn: sqlite3.Connection, file_type: str, process_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT page_count, avg_confidence FROM confidence_metrics "
        "WHERE file_type = ? AND process_type = ?",
        (file_type, process_type),
    ).fetchone()


def insert_confidence_metrics(
    conn: sqlite3.Connection,
    file_type: str,
    process_type: str,
    page_count: int,
    avg_confidence: float,
    updated_at: str,
) -> None:
    conn.execute(
        "INSERT INTO confidence_metrics "
        "(file_type, process_type, page_count, avg_confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (file_type, process_type, page_count, avg_confidence, updated_at),
    )


def update_confidence_metrics(
    conn: sqlite3.Connection,
    file_type: str,
    process_type: str,
    page_count: int,
    avg_confidence: float,
    updated_at: str,
) -> None:
    conn.execute(
        "UPDATE confidence_metrics SET page_count = ?, avg_confidence = ?, updated_at = ? "
        "WHERE file_type = ? AND process_type = ?",
        (page_count, avg_confidence, updated_at, file_type, process_type),
    )


def list_processing_metrics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT file_type, size_bucket, document_count, avg_duration_seconds, "
        "avg_peak_memory_mb, avg_cpu_percent, updated_at FROM processing_metrics "
        "ORDER BY file_type, size_bucket"
    ).fetchall()


def list_confidence_metrics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT file_type, process_type, page_count, avg_confidence, updated_at "
        "FROM confidence_metrics ORDER BY file_type, process_type"
    ).fetchall()


def clear_processing_metrics(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM processing_metrics")


def clear_confidence_metrics(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM confidence_metrics")


def get_processing_metrics_avg_duration_by_file_type(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Per-file_type average duration, weighted by each size bucket's document_count."""
    return conn.execute(
        "SELECT file_type, "
        "SUM(avg_duration_seconds * document_count) / SUM(document_count) "
        "AS avg_duration_seconds "
        "FROM processing_metrics WHERE document_count > 0 GROUP BY file_type"
    ).fetchall()
