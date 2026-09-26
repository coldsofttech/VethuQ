"""Small persisted key-value settings store for VethuQ."""

from __future__ import annotations

import sqlite3

GPU_ENABLED_KEY = "gpu_enabled"
SEARCH_SNIPPET_CONTEXT_CHARS_KEY = "search_snippet_context_chars"
DEFAULT_SEARCH_SNIPPET_CONTEXT_CHARS = 80


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


def get_search_snippet_context_chars(conn: sqlite3.Connection) -> int:
    """How many characters of context `search` shows around a match. 80 by default."""
    value = get_setting(conn, SEARCH_SNIPPET_CONTEXT_CHARS_KEY)
    return int(value) if value is not None else DEFAULT_SEARCH_SNIPPET_CONTEXT_CHARS


def set_search_snippet_context_chars(conn: sqlite3.Connection, chars: int) -> None:
    if chars < 0:
        raise ValueError("chars must be non-negative")
    set_setting(conn, SEARCH_SNIPPET_CONTEXT_CHARS_KEY, str(chars))
