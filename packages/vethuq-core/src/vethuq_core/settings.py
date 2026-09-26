"""Small persisted key-value settings store for VethuQ."""

from __future__ import annotations

import sqlite3

GPU_ENABLED_KEY = "gpu_enabled"


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def is_gpu_enabled(conn: sqlite3.Connection) -> bool:
    """Whether OCR should attempt to use the GPU. Disabled by default."""
    return get_setting(conn, GPU_ENABLED_KEY) == "true"


def set_gpu_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    set_setting(conn, GPU_ENABLED_KEY, "true" if enabled else "false")
