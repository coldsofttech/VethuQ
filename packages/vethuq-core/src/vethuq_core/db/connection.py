"""SQLite connection and schema bootstrap for VethuQ's local data store."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "VethuQ"
DB_FILENAME = "vethuq.db"

SCHEMA_VERSION = 17

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
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    document_id INTEGER NOT NULL REFERENCES documents(id),
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
    workers INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS processing_metrics (
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
    size_bucket TEXT NOT NULL CHECK (size_bucket IN ('small', 'medium', 'large')),
    document_count INTEGER NOT NULL DEFAULT 0,
    avg_duration_seconds REAL NOT NULL DEFAULT 0,
    avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
    avg_cpu_percent REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (file_type, size_bucket)
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


def default_db_path() -> Path:
    """Return the per-user path where VethuQ's SQLite database lives."""
    data_dir = Path(user_data_dir(APP_NAME, appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / DB_FILENAME


def connect(db_path: Path | None = None, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open a connection to the VethuQ database, creating the schema if needed.

    `check_same_thread=False` is only for a connection that's deliberately
    shared across threads (background indexing with worker threads - see
    `vethuq_core.ocr.run_ocr_batch`'s `db_lock`, which serializes every use
    of such a connection since SQLite connections aren't safe for
    unsynchronized concurrent access on their own).
    """
    path = db_path or default_db_path()
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
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
    # Created after the table (and any migration adding these columns to it)
    # rather than inline in `_SCHEMA`, since that script runs before
    # migrations and would otherwise fail against a pre-migration table.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_index_checksum ON document_index(checksum)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_index_document_id "
        "ON document_index(document_id)"
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
                "ALTER TABLE processing_metrics ADD COLUMN avg_cpu_percent REAL NOT NULL DEFAULT 0"
            )
    if from_version < 14:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(index_runs)")}
        if "workers" not in columns:
            conn.execute("ALTER TABLE index_runs ADD COLUMN workers INTEGER")
    if from_version < 15:
        # avg_confidence used to live on processing_metrics, blended across a
        # file_type's native/ocr/mixed pages - since native pages are ~100%
        # confidence, that blend diluted the OCR/mixed signal. Confidence now
        # lives in its own table keyed by (file_type, process_type), backfilled
        # below from the page-level history that's still in pdf_pages/image_pages
        # rather than from the old blended average.
        conn.execute(
            """
            CREATE TABLE processing_metrics_new (
                file_type TEXT PRIMARY KEY CHECK (file_type IN ('pdf', 'image')),
                document_count INTEGER NOT NULL DEFAULT 0,
                avg_duration_seconds REAL NOT NULL DEFAULT 0,
                avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
                avg_cpu_percent REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO processing_metrics_new "
            "(file_type, document_count, avg_duration_seconds, avg_peak_memory_mb, "
            "avg_cpu_percent, updated_at) "
            "SELECT file_type, document_count, avg_duration_seconds, avg_peak_memory_mb, "
            "avg_cpu_percent, updated_at FROM processing_metrics"
        )
        conn.execute("DROP TABLE processing_metrics")
        conn.execute("ALTER TABLE processing_metrics_new RENAME TO processing_metrics")

        # `_ensure_schema` already created `confidence_metrics` via the
        # `CREATE TABLE IF NOT EXISTS` in `_SCHEMA` before migrations run.
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO confidence_metrics "
            "(file_type, process_type, page_count, avg_confidence, updated_at) "
            "SELECT 'pdf', source, COUNT(*), AVG(confidence), ? "
            "FROM pdf_pages GROUP BY source",
            (now,),
        )
        conn.execute(
            "INSERT INTO confidence_metrics "
            "(file_type, process_type, page_count, avg_confidence, updated_at) "
            "SELECT 'image', 'ocr', COUNT(*), AVG(confidence), ? "
            "FROM image_pages HAVING COUNT(*) > 0",
            (now,),
        )
    if from_version < 16:
        # processing_metrics used to average duration/memory/cpu per file_type
        # alone, blending a 20KB image with a 10MB one - not granular enough
        # for the "auto" scheduler to tell whether the *next specific* pending
        # file would tip the machine over its resource budget. size_bucket
        # splits each file_type's average by rough file size instead; the
        # thresholds here (bytes) must match `ocr._size_bucket`.
        conn.execute(
            """
            CREATE TABLE processing_metrics_new (
                file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
                size_bucket TEXT NOT NULL CHECK (size_bucket IN ('small', 'medium', 'large')),
                document_count INTEGER NOT NULL DEFAULT 0,
                avg_duration_seconds REAL NOT NULL DEFAULT 0,
                avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
                avg_cpu_percent REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (file_type, size_bucket)
            )
            """
        )
        # The existing per-file_type average is carried over as-is into the
        # 'medium' bucket (the old data doesn't know which sizes produced it,
        # so there's nothing more precise to assign it to) - future documents
        # then fold into whichever bucket their own size actually lands in.
        conn.execute(
            """
            INSERT INTO processing_metrics_new
                (file_type, size_bucket, document_count, avg_duration_seconds,
                 avg_peak_memory_mb, avg_cpu_percent, updated_at)
            SELECT file_type, 'medium', document_count, avg_duration_seconds,
                avg_peak_memory_mb, avg_cpu_percent, updated_at
            FROM processing_metrics
            """
        )
        conn.execute("DROP TABLE processing_metrics")
        conn.execute("ALTER TABLE processing_metrics_new RENAME TO processing_metrics")
    if from_version < 17:
        # Introduces logical document identity (`documents`), separate from
        # the physical file rows in `document_index`. Every document_index
        # row gets a `document_id` - duplicate content (previously chained
        # via `duplicate_of_id` to one specific file row) now instead shares
        # a `documents` row directly, so the group survives independently of
        # which physical row happens to represent it.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        if "document_id" not in columns:
            conn.execute(
                "ALTER TABLE document_index ADD COLUMN document_id "
                "INTEGER REFERENCES documents(id)"
            )

        now = datetime.now(UTC).isoformat()
        # Every root row (one that isn't itself a duplicate) becomes its own
        # logical document; a duplicate inherits its root's. A database that
        # was never actually migrated through version 9 (so never had
        # `duplicate_of_id` at all - only possible here via a hand-built
        # fixture, since a real upgrade always ran that migration in order)
        # has no duplicate bookkeeping to carry over, so every row is a root.
        has_duplicate_of_id = "duplicate_of_id" in columns
        roots = conn.execute(
            "SELECT id FROM document_index WHERE duplicate_of_id IS NULL"
            if has_duplicate_of_id
            else "SELECT id FROM document_index"
        ).fetchall()
        for root in roots:
            new_document_id = conn.execute(
                "INSERT INTO documents (created_at) VALUES (?)", (now,)
            ).lastrowid
            if has_duplicate_of_id:
                conn.execute(
                    "UPDATE document_index SET document_id = ? "
                    "WHERE id = ? OR duplicate_of_id = ?",
                    (new_document_id, root["id"], root["id"]),
                )
            else:
                conn.execute(
                    "UPDATE document_index SET document_id = ? WHERE id = ?",
                    (new_document_id, root["id"]),
                )

        # Rebuild to make `document_id` NOT NULL and drop `duplicate_of_id` -
        # SQLite can't add a NOT NULL constraint or drop a column in place,
        # so this follows the same rebuild-the-table pattern the version-11
        # migration used for its CHECK constraint change. `PRAGMA foreign_keys`
        # is a no-op inside a pending transaction, and the backfill INSERTs/
        # UPDATEs above already opened one - commit first so it actually takes.
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE document_index_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                document_id INTEGER NOT NULL REFERENCES documents(id),
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
                mtime REAL,
                removed_at TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                peak_memory_mb REAL,
                cpu_percent REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO document_index_new "
            "(id, source_id, document_id, file_path, file_type, status, error_message, "
            "indexed_at, started_at, completed_at, file_size_bytes, checksum, mtime, "
            "removed_at, retry_count, peak_memory_mb, cpu_percent) "
            "SELECT id, source_id, document_id, file_path, file_type, status, error_message, "
            "indexed_at, started_at, completed_at, file_size_bytes, checksum, mtime, "
            "removed_at, retry_count, peak_memory_mb, cpu_percent FROM document_index"
        )
        conn.execute("DROP TABLE document_index")
        conn.execute("ALTER TABLE document_index_new RENAME TO document_index")
        conn.execute("PRAGMA foreign_keys = ON")
