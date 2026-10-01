"""SQL for the `settings` key-value table."""

from __future__ import annotations

import sqlite3


class Settings:
    @staticmethod
    def get_value(conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else None

    @staticmethod
    def upsert(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
