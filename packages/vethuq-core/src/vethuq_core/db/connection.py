"""SQLite connection and schema bootstrap for VethuQ's local data store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

from vethuq_core.db.migration import Migration


class Db:
    APP_NAME = "VethuQ"
    DB_FILENAME = "vethuq.db"

    SCHEMA_VERSION = 24

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

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    file_path TEXT
);

CREATE TABLE IF NOT EXISTS document_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    document_id INTEGER NOT NULL REFERENCES documents(id),
    file_path TEXT NOT NULL UNIQUE,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'indexed', 'error', 'removed')),
    error_message TEXT,
    indexed_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    file_size_bytes INTEGER,
    sha256 TEXT,
    mtime REAL,
    created_at TEXT,
    modified_at TEXT,
    removed_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    peak_memory_mb REAL,
    cpu_percent REAL
);

CREATE TABLE IF NOT EXISTS pdf_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    page_number INTEGER NOT NULL,
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'ocr' CHECK (source IN ('native', 'ocr', 'mixed')),
    ocr_engine TEXT,
    language TEXT,
    image_width INTEGER,
    image_height INTEGER,
    ocr_phase INTEGER NOT NULL DEFAULT 1,
    ocr_angles TEXT NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS image_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    ocr_engine TEXT,
    language TEXT,
    image_width INTEGER,
    image_height INTEGER,
    ocr_phase INTEGER NOT NULL DEFAULT 1,
    ocr_angles TEXT NOT NULL DEFAULT '0'
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
    workers INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS processing_metrics (
    phase INTEGER NOT NULL DEFAULT 1,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
    size_bucket TEXT NOT NULL CHECK (size_bucket IN ('small', 'medium', 'large')),
    document_count INTEGER NOT NULL DEFAULT 0,
    avg_duration_seconds REAL NOT NULL DEFAULT 0,
    avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
    avg_cpu_percent REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (phase, file_type, size_bucket)
);

-- Phase 1 (quick) timings live on document_index; this holds the deeper
-- phases (2+), one row per logical document and phase.
CREATE TABLE IF NOT EXISTS document_phases (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    phase INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    indexed_at TEXT,
    duration_seconds REAL NOT NULL DEFAULT 0,
    peak_memory_mb REAL,
    cpu_percent REAL,
    PRIMARY KEY (document_id, phase)
);

CREATE TABLE IF NOT EXISTS confidence_metrics (
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
    process_type TEXT NOT NULL CHECK (process_type IN ('native', 'ocr', 'mixed')),
    page_count INTEGER NOT NULL DEFAULT 0,
    avg_confidence REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (file_type, process_type)
);
"""

    @staticmethod
    def default_db_path() -> Path:
        """Return the per-user path where VethuQ's SQLite database lives."""
        data_dir = Path(user_data_dir(Db.APP_NAME, appauthor=False))
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / Db.DB_FILENAME

    @staticmethod
    def connect(
        db_path: Path | None = None, *, check_same_thread: bool = True
    ) -> sqlite3.Connection:
        """Open a connection to the VethuQ database, creating the schema if needed.

        `check_same_thread=False` is only for a connection that's deliberately
        shared across threads (background indexing with worker threads - see
        `vethuq_core.ocr.run_ocr_batch`'s `db_lock`, which serializes every use
        of such a connection since SQLite connections aren't safe for
        unsynchronized concurrent access on their own).
        """
        path = db_path or Db.default_db_path()
        conn = sqlite3.connect(path, check_same_thread=check_same_thread)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        Db._ensure_schema(conn)

        from vethuq_core.source import Sources

        Sources.purge_expired_sources(conn)
        Sources.purge_expired_documents(conn)
        return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(Db._SCHEMA)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (Db.SCHEMA_VERSION,))
        elif row["version"] < Db.SCHEMA_VERSION:
            Migration.schema(conn, from_version=row["version"])
            conn.execute("UPDATE schema_version SET version = ?", (Db.SCHEMA_VERSION,))
        # Created after the table (and any migration adding these columns to it)
        # rather than inline in `_SCHEMA`, since that script runs before
        # migrations and would otherwise fail against a pre-migration table.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_index_sha256 ON document_index(sha256)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_index_document_id "
            "ON document_index(document_id)"
        )
        conn.commit()
