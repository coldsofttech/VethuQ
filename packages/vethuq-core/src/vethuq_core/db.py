"""SQLite connection and schema bootstrap for VethuQ's local data store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "VethuQ"
DB_FILENAME = "vethuq.db"

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN ('file', 'folder')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'indexed', 'error', 'removed')),
    added_at TEXT NOT NULL,
    last_scanned_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);
"""


def default_db_path() -> Path:
    """Return the per-user path where VethuQ's SQLite database lives."""
    data_dir = Path(user_data_dir(APP_NAME, appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / DB_FILENAME


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection to the VethuQ database, creating the schema if needed."""
    path = db_path or default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()
