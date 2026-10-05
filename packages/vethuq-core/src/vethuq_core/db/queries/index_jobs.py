"""SQL for the `index_jobs` table (index runs queued for the background service)."""

from __future__ import annotations

import sqlite3


class IndexJobs:
    @staticmethod
    def enqueue(
        conn: sqlite3.Connection,
        target: str | None,
        mode: str,
        languages: str | None,
        requested_at: str,
    ) -> int:
        cursor = conn.execute(
            "INSERT INTO index_jobs (target, mode, languages, status, requested_at) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (target, mode, languages, requested_at),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @staticmethod
    def list_jobs(
        conn: sqlite3.Connection, statuses: tuple[str, ...] | None, limit: int
    ) -> list[sqlite3.Row]:
        """Jobs in the given statuses (all if None), oldest first for 'queued', else newest."""
        if statuses is None:
            return conn.execute(
                "SELECT * FROM index_jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        marks = ",".join("?" for _ in statuses)
        order = "ASC" if statuses == ("queued",) else "DESC"
        return conn.execute(
            f"SELECT * FROM index_jobs WHERE status IN ({marks}) ORDER BY id {order} LIMIT ?",
            (*statuses, limit),
        ).fetchall()

    @staticmethod
    def claim_next(conn: sqlite3.Connection, started_at: str) -> sqlite3.Row | None:
        """Mark the oldest queued job running and return it, or None when the queue is empty."""
        row = conn.execute(
            "SELECT * FROM index_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE index_jobs SET status = 'running', started_at = ? "
            "WHERE id = ? AND status = 'queued'",
            (started_at, row["id"]),
        )
        return conn.execute("SELECT * FROM index_jobs WHERE id = ?", (row["id"],)).fetchone()

    @staticmethod
    def finish(
        conn: sqlite3.Connection, job_id: int, status: str, finished_at: str, error: str | None
    ) -> None:
        conn.execute(
            "UPDATE index_jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
            (status, finished_at, error, job_id),
        )

    @staticmethod
    def requeue(conn: sqlite3.Connection, job_id: int) -> None:
        conn.execute(
            "UPDATE index_jobs SET status = 'queued', started_at = NULL WHERE id = ?", (job_id,)
        )

    @staticmethod
    def requeue_running(conn: sqlite3.Connection) -> int:
        """Put jobs a dead service left 'running' back in the queue; returns how many."""
        cursor = conn.execute(
            "UPDATE index_jobs SET status = 'queued', started_at = NULL WHERE status = 'running'"
        )
        return cursor.rowcount

    @staticmethod
    def cancel_queued(conn: sqlite3.Connection, finished_at: str) -> int:
        cursor = conn.execute(
            "UPDATE index_jobs SET status = 'cancelled', finished_at = ? WHERE status = 'queued'",
            (finished_at,),
        )
        return cursor.rowcount

    @staticmethod
    def prune_finished(conn: sqlite3.Connection, keep: int) -> None:
        """Delete all but the `keep` most recent finished jobs."""
        conn.execute(
            "DELETE FROM index_jobs WHERE status NOT IN ('queued', 'running') AND id NOT IN ("
            "SELECT id FROM index_jobs WHERE status NOT IN ('queued', 'running') "
            "ORDER BY id DESC LIMIT ?)",
            (keep,),
        )
