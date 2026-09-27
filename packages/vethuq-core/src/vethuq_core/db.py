"""SQLite connection and schema bootstrap for VethuQ's local data store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "VethuQ"
DB_FILENAME = "vethuq.db"

SCHEMA_VERSION = 13

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
        CHECK (status IN ('pending', 'indexed', 'error', 'removed')),
    error_message TEXT,
    indexed_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    file_size_bytes INTEGER,
    checksum TEXT,
    duplicate_of_id INTEGER REFERENCES document_index(id),
    mtime REAL,
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
    image_height INTEGER
);

CREATE TABLE IF NOT EXISTS image_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    ocr_text TEXT NOT NULL,
    confidence REAL NOT NULL,
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
    avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
    avg_cpu_percent REAL NOT NULL DEFAULT 0,
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

    from vethuq_core.sources import purge_expired_removed_documents, purge_expired_removed_sources

    purge_expired_removed_sources(conn)
    purge_expired_removed_documents(conn)
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
    if from_version < 10:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        if "mtime" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN mtime REAL")
    if from_version < 11:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        if "removed_at" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN removed_at TEXT")
        # SQLite can't widen a CHECK constraint in place - rebuild the table
        # (the documented SQLite pattern for constraint changes) so `status`
        # also allows 'removed', for a file that's gone missing from a
        # still-active source without the whole source being removed.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE document_index_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'indexed', 'error', 'removed')),
                error_message TEXT,
                indexed_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                file_size_bytes INTEGER,
                checksum TEXT,
                duplicate_of_id INTEGER REFERENCES document_index_new(id),
                mtime REAL,
                removed_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO document_index_new "
            "(id, source_id, file_path, file_type, status, error_message, indexed_at, "
            "started_at, completed_at, file_size_bytes, checksum, duplicate_of_id, mtime, "
            "removed_at) "
            "SELECT id, source_id, file_path, file_type, status, error_message, indexed_at, "
            "started_at, completed_at, file_size_bytes, checksum, duplicate_of_id, mtime, "
            "removed_at FROM document_index"
        )
        conn.execute("DROP TABLE document_index")
        conn.execute("ALTER TABLE document_index_new RENAME TO document_index")
        conn.execute("PRAGMA foreign_keys = ON")
    if from_version < 12:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        if "retry_count" not in columns:
            conn.execute(
                "ALTER TABLE document_index ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"
            )
        if "peak_memory_mb" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN peak_memory_mb REAL")
        if "cpu_percent" not in columns:
            conn.execute("ALTER TABLE document_index ADD COLUMN cpu_percent REAL")
        for table in ("pdf_pages", "image_pages"):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "ocr_engine" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN ocr_engine TEXT")
            if "language" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN language TEXT")
            if "image_width" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN image_width INTEGER")
            if "image_height" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN image_height INTEGER")
    if from_version < 13:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
        if "avg_peak_memory_mb" not in columns:
            conn.execute(
                "ALTER TABLE processing_metrics ADD COLUMN avg_peak_memory_mb "
                "REAL NOT NULL DEFAULT 0"
            )
        if "avg_cpu_percent" not in columns:
            conn.execute(
                "ALTER TABLE processing_metrics ADD COLUMN avg_cpu_percent "
                "REAL NOT NULL DEFAULT 0"
            )
