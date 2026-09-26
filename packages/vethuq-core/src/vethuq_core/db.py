"""SQLite connection and schema bootstrap for VethuQ's local data store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "VethuQ"
DB_FILENAME = "vethuq.db"

SCHEMA_VERSION = 9

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
    is_active INTEGER NOT NULL DEFAULT 1,
    removed_at TEXT
);

CREATE TABLE IF NOT EXISTS document_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    file_path TEXT NOT NULL UNIQUE,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'indexed', 'error')),
    error_message TEXT,
    indexed_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    file_size_bytes INTEGER,
    checksum TEXT,
    duplicate_of_id INTEGER REFERENCES document_index(id)
);

CREATE TABLE IF NOT EXISTS pdf_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    page_number INTEGER NOT NULL,
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'ocr' CHECK (source IN ('native', 'ocr', 'mixed'))
);

CREATE TABLE IF NOT EXISTS image_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT,
    mode TEXT NOT NULL DEFAULT 'run' CHECK (mode IN ('run', 'restart')),
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'stopped', 'failed')),
    pid INTEGER,
    total_files INTEGER NOT NULL DEFAULT 0,
    processed_files INTEGER NOT NULL DEFAULT 0,
    failed_files INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS processing_metrics (
    file_type TEXT PRIMARY KEY CHECK (file_type IN ('pdf', 'image')),
    document_count INTEGER NOT NULL DEFAULT 0,
    avg_duration_seconds REAL NOT NULL DEFAULT 0,
    avg_confidence REAL NOT NULL DEFAULT 0,
    pages_native INTEGER NOT NULL DEFAULT 0,
    pages_ocr INTEGER NOT NULL DEFAULT 0,
    pages_mixed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
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

    from vethuq_core.sources import purge_expired_removed_sources

    purge_expired_removed_sources(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif row["version"] < SCHEMA_VERSION:
        _migrate_schema(conn, from_version=row["version"])
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    # Created after the table (and any migration adding `checksum` to it)
    # rather than inline in `_SCHEMA`, since that script runs before
    # migrations and would otherwise fail against a pre-migration table.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_index_checksum ON document_index(checksum)"
    )
    conn.commit()


def _migrate_schema(conn: sqlite3.Connection, *, from_version: int) -> None:
    if from_version < 3:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(pdf_pages)")}
        if "source" not in columns:
            conn.execute("ALTER TABLE pdf_pages ADD COLUMN source TEXT NOT NULL DEFAULT 'ocr'")
    if from_version < 5:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        if "started_at" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN started_at TEXT")
        if "completed_at" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN completed_at TEXT")
    if from_version < 6:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(index_runs)")}
        if "mode" not in columns:
            conn.execute("ALTER TABLE index_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'run'")
    if from_version < 7:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
        if "removed_at" not in columns:
            conn.execute("ALTER TABLE sources ADD COLUMN removed_at TEXT")
    if from_version < 8:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        if "file_size_bytes" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN file_size_bytes INTEGER")
    if from_version < 9:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        if "checksum" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN checksum TEXT")
        if "duplicate_of_id" not in columns:
            conn.execute(
                "ALTER TABLE document_index ADD COLUMN duplicate_of_id "
                "INTEGER REFERENCES document_index(id)"
            )
