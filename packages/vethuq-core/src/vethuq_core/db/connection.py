"""SQLite connection and schema bootstrap for VethuQ's local data store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

from vethuq_core.db.migration import Migration


class Db:
    APP_NAME = "VethuQ"
    DB_FILENAME = "vethuq.db"

    # How long a writer waits on a lock held by another connection (WAL still
    # serializes writers against each other) before raising "database is locked" -
    # generous enough to ride out a concurrent writer's transaction (e.g. the
    # desktop app's background indexing overlapping a CLI command against the
    # same database) rather than failing immediately.
    BUSY_TIMEOUT_MS = 5000

    SCHEMA_VERSION = 27

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
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'doc', 'docx', 'rtf')),
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

-- Word-processor documents (.doc/.docx/.rtf): one row per document, holding its native
-- text plus the OCR text of its embedded images. There's no page layout to key on, and
-- nothing here is deepened (no ocr_phase/ocr_angles) - see `vethuq_core.ocr.DocxReader`.
CREATE TABLE IF NOT EXISTS office_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'native' CHECK (source IN ('native', 'ocr', 'mixed')),
    ocr_engine TEXT,
    language TEXT,
    image_width INTEGER,
    image_height INTEGER
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
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'doc', 'docx', 'rtf')),
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
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'doc', 'docx', 'rtf')),
    process_type TEXT NOT NULL CHECK (process_type IN ('native', 'ocr', 'mixed')),
    page_count INTEGER NOT NULL DEFAULT 0,
    avg_confidence REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (file_type, process_type)
);

-- Full-text index over ocr_text, one per pages table, so `vethuq_core.search`
-- can query matching pages through SQLite's trigram index instead of
-- scanning every indexed page's text in Python. `tokenize='trigram'`
-- (rather than FTS5's default word tokenizer) keeps the same "any substring,
-- anywhere, case-insensitively" matching that predates this index (e.g. a
-- query of "arge" must still match "large") - achieved by querying these
-- tables with LIKE '%...%' instead of MATCH, which SQLite still resolves
-- through the trigram index. Declared as external-content tables
-- (content=/content_rowid=) so ocr_text isn't duplicated on disk; the
-- triggers below are what keep them in sync, since an external-content FTS5
-- index doesn't update itself.
CREATE VIRTUAL TABLE IF NOT EXISTS pdf_pages_fts USING fts5(
    ocr_text,
    content='pdf_pages',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS pdf_pages_fts_ai AFTER INSERT ON pdf_pages BEGIN
    INSERT INTO pdf_pages_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_pages_fts_ad AFTER DELETE ON pdf_pages BEGIN
    INSERT INTO pdf_pages_fts(pdf_pages_fts, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_pages_fts_au AFTER UPDATE ON pdf_pages BEGIN
    INSERT INTO pdf_pages_fts(pdf_pages_fts, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
    INSERT INTO pdf_pages_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS image_pages_fts USING fts5(
    ocr_text,
    content='image_pages',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS image_pages_fts_ai AFTER INSERT ON image_pages BEGIN
    INSERT INTO image_pages_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS image_pages_fts_ad AFTER DELETE ON image_pages BEGIN
    INSERT INTO image_pages_fts(image_pages_fts, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS image_pages_fts_au AFTER UPDATE ON image_pages BEGIN
    INSERT INTO image_pages_fts(image_pages_fts, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
    INSERT INTO image_pages_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS office_pages_fts USING fts5(
    ocr_text,
    content='office_pages',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS office_pages_fts_ai AFTER INSERT ON office_pages BEGIN
    INSERT INTO office_pages_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS office_pages_fts_ad AFTER DELETE ON office_pages BEGIN
    INSERT INTO office_pages_fts(office_pages_fts, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS office_pages_fts_au AFTER UPDATE ON office_pages BEGIN
    INSERT INTO office_pages_fts(office_pages_fts, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
    INSERT INTO office_pages_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;
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
        `vethuq_core.ocr.Quick.run_batch`'s `db_lock`, which serializes every use
        of such a connection since SQLite connections aren't safe for
        unsynchronized concurrent access on their own).

        WAL journal mode lets the database recover cleanly after an application
        crash mid-write (rolling back an incomplete transaction from the WAL file
        instead of leaving the main db file in a torn state), and - combined with
        `busy_timeout` - lets readers and writers on separate connections
        (including from separate processes, e.g. the desktop app's background
        indexing alongside a CLI command) proceed without racing into "database
        is locked" errors.
        """
        path = db_path or Db.default_db_path()
        conn = sqlite3.connect(path, check_same_thread=check_same_thread)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {Db.BUSY_TIMEOUT_MS}")
        Db._ensure_schema(conn, path)

        from vethuq_core.source import Sources

        Sources.purge_expired_sources(conn)
        Sources.purge_expired_documents(conn)
        return conn

    @staticmethod
    def _backup_before_migration(conn: sqlite3.Connection, db_path: Path) -> None:
        """Snapshot the pre-migration database to `<db_path>.bkp`.

        Goes through SQLite's own backup API rather than copying `db_path` on
        disk, so the snapshot is consistent even though - under WAL - some
        already-committed data may currently live only in the `-wal` file rather
        than in `db_path` itself. Runs before `Migration.schema` so a failed or
        bad migration can be rolled back to this pre-migration copy.
        """
        backup_path = Path(f"{db_path}.bkp")
        backup_conn = sqlite3.connect(backup_path)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection, db_path: Path) -> None:
        conn.executescript(Db._SCHEMA)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (Db.SCHEMA_VERSION,))
        elif row["version"] < Db.SCHEMA_VERSION:
            Db._backup_before_migration(conn, db_path)
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
