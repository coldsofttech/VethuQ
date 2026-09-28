"""SQL for the `index_runs` table."""

from __future__ import annotations

import sqlite3


def list_index_runs(conn: sqlite3.Connection, target: str | None, limit: int) -> list[sqlite3.Row]:
    """Return past index runs, most recent first, optionally filtered to one target.

    A run over "all sources" (`target` column IS NULL) covered every source,
    so it's included alongside runs targeted at just the given `target`.
    """
    if target is None:
        return conn.execute(
            "SELECT * FROM index_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return conn.execute(
        "SELECT * FROM index_runs WHERE target = ? OR target IS NULL "
        "ORDER BY started_at DESC LIMIT ?",
        (target, limit),
    ).fetchall()


def insert_index_run(
    conn: sqlite3.Connection,
    target: str | None,
    mode: str,
    pid: int,
    total_files: int,
    workers: int,
    started_at: str,
) -> int:
    cursor = conn.execute(
        "INSERT INTO index_runs "
        "(target, mode, status, pid, total_files, workers, started_at) "
        "VALUES (?, ?, 'running', ?, ?, ?, ?)",
        (target, mode, pid, total_files, workers, started_at),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def fail_all_running_index_runs(conn: sqlite3.Connection, completed_at: str) -> None:
    conn.execute(
        "UPDATE index_runs SET status = 'failed', completed_at = ? WHERE status = 'running'",
        (completed_at,),
    )


def end_running_index_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    processed_files: int,
    failed_files: int,
    completed_at: str,
) -> None:
    conn.execute(
        "UPDATE index_runs SET status = ?, processed_files = ?, failed_files = ?, "
        "completed_at = ? WHERE id = ? AND status = 'running'",
        (status, processed_files, failed_files, completed_at, run_id),
    )


def fail_index_run(conn: sqlite3.Connection, run_id: int, completed_at: str) -> None:
    conn.execute(
        "UPDATE index_runs SET status = 'failed', completed_at = ? WHERE id = ?",
        (completed_at, run_id),
    )
