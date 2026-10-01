"""SQL for the `sources` table."""

from __future__ import annotations

import sqlite3


class Source:
    @staticmethod
    def get_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM sources WHERE path = ?", (path,)).fetchone()

    @staticmethod
    def get_by_id(conn: sqlite3.Connection, source_id: int) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    @staticmethod
    def get_active_by_id(conn: sqlite3.Connection, source_id: int) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM sources WHERE id = ? AND is_active = 1", (source_id,)
        ).fetchone()

    @staticmethod
    def get_active_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM sources WHERE path = ? AND is_active = 1", (path,)
        ).fetchone()

    @staticmethod
    def reactivate(
        conn: sqlite3.Connection, source_id: int, source_type: str, added_at: str
    ) -> None:
        conn.execute(
            """
            UPDATE sources
            SET source_type = ?, status = 'pending', added_at = ?,
                last_scanned_at = NULL, is_active = 1, removed_at = NULL
            WHERE id = ?
            """,
            (source_type, added_at, source_id),
        )

    @staticmethod
    def insert(conn: sqlite3.Connection, path: str, source_type: str, added_at: str) -> int:
        cursor = conn.execute(
            """
            INSERT INTO sources (path, source_type, status, added_at, is_active)
            VALUES (?, ?, 'pending', ?, 1)
            """,
            (path, source_type, added_at),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @staticmethod
    def list_rows(conn: sqlite3.Connection, include_inactive: bool) -> list[sqlite3.Row]:
        query = "SELECT * FROM sources"
        if not include_inactive:
            query += " WHERE is_active = 1"
        query += " ORDER BY added_at DESC"
        return conn.execute(query).fetchall()

    @staticmethod
    def soft_delete(conn: sqlite3.Connection, source_id: int, removed_at: str) -> None:
        conn.execute(
            "UPDATE sources SET is_active = 0, status = 'removed', removed_at = ? WHERE id = ?",
            (removed_at, source_id),
        )

    @staticmethod
    def list_expired_removed(conn: sqlite3.Connection, cutoff: str) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT id, path FROM sources "
            "WHERE status = 'removed' AND removed_at IS NOT NULL AND removed_at <= ?",
            (cutoff,),
        ).fetchall()

    @staticmethod
    def delete_by_ids(conn: sqlite3.Connection, source_ids: list[int]) -> None:
        placeholders = ",".join("?" * len(source_ids))
        conn.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", source_ids)

    @staticmethod
    def clear_index_run_targets(conn: sqlite3.Connection, stale_targets: list[str]) -> None:
        placeholders = ",".join("?" * len(stale_targets))
        conn.execute(
            f"UPDATE index_runs SET target = NULL WHERE target IN ({placeholders})", stale_targets
        )

    @staticmethod
    def update_scan_status(
        conn: sqlite3.Connection, source_id: int, status: str, last_scanned_at: str
    ) -> None:
        conn.execute(
            "UPDATE sources SET status = ?, last_scanned_at = ? WHERE id = ?",
            (status, last_scanned_at, source_id),
        )
