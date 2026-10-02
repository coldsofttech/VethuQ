"""Schema migrations for VethuQ's local SQLite database."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


class Migration:
    @staticmethod
    def _lacks_document_identity(conn: sqlite3.Connection) -> bool:
        """Return whether `document_index` still predates logical document identity."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        return "document_id" not in columns or "duplicate_of_id" in columns

    @staticmethod
    def schema(conn: sqlite3.Connection, *, from_version: int) -> None:
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
                    "ALTER TABLE processing_metrics "
                    "ADD COLUMN avg_cpu_percent REAL NOT NULL DEFAULT 0"
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
        if from_version < 18:
            # (Schema 17 was used by both the document-identity and OCR-phase work;
            # re-running this guarded step for 17 keeps either lineage's databases whole.)
            # Pages indexed so far only had the upright (0 degree) pass, which is
            # exactly what the column defaults record - so they're picked up by
            # deeper OCR phases (see `ocr.OCR_PHASE_ANGLES`) when the engine
            # setting asks for them.
            for table in ("pdf_pages", "image_pages"):
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if "ocr_phase" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN ocr_phase INTEGER NOT NULL DEFAULT 1"
                    )
                if "ocr_angles" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN ocr_angles TEXT NOT NULL DEFAULT '0'"
                    )
            # Indexing settings now share an `index_` prefix in the settings table.
            # A value saved under an old key moves to the new one; if the new key
            # somehow already has a value, that one wins and the old row is dropped.
            for old_key, new_key in (
                ("removed_source_retention_minutes", "index_removed_source_retention_minutes"),
                ("ocr_retry_attempts", "index_ocr_retry_attempts"),
                ("thread_workers", "index_thread_workers"),
                ("stale_lock", "index_stale_lock"),
                ("ocr_engine", "index_engine"),
            ):
                conn.execute(
                    "UPDATE OR IGNORE settings SET key = ? WHERE key = ?", (new_key, old_key)
                )
                conn.execute("DELETE FROM settings WHERE key = ?", (old_key,))
        if from_version < 19:
            # Native-text PDF pages were briefly recorded at the final phase (3) as
            # "nothing left to do", which read as if deep OCR had run on them. They're
            # quick-phase pages like any other; deeper phases skip them by `source`.
            conn.execute(
                "UPDATE pdf_pages SET ocr_phase = 1 WHERE source = 'native' AND ocr_phase > 1"
            )
        if from_version < 20:
            # processing_metrics now tracks every OCR phase, not just the quick first
            # pass: `phase` joins the primary key, and what's there so far is phase 1.
            # (`document_phases`, for the deeper phases, came from `_SCHEMA` above.)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
            if "phase" not in columns:
                conn.execute(
                    """
                    CREATE TABLE processing_metrics_new (
                        phase INTEGER NOT NULL DEFAULT 1,
                        file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
                        size_bucket TEXT NOT NULL
                            CHECK (size_bucket IN ('small', 'medium', 'large')),
                        document_count INTEGER NOT NULL DEFAULT 0,
                        avg_duration_seconds REAL NOT NULL DEFAULT 0,
                        avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
                        avg_cpu_percent REAL NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (phase, file_type, size_bucket)
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO processing_metrics_new "
                    "(phase, file_type, size_bucket, document_count, avg_duration_seconds, "
                    "avg_peak_memory_mb, avg_cpu_percent, updated_at) "
                    "SELECT 1, file_type, size_bucket, document_count, avg_duration_seconds, "
                    "avg_peak_memory_mb, avg_cpu_percent, updated_at FROM processing_metrics"
                )
                conn.execute("DROP TABLE processing_metrics")
                conn.execute("ALTER TABLE processing_metrics_new RENAME TO processing_metrics")
        if from_version < 21 and Migration._lacks_document_identity(conn):
            # (Schema 17 also meant "has document identity" on an earlier lineage of
            # this branch, so those databases skip this - nothing to convert.)
            # Introduces logical document identity (`documents`), separate from
            # the physical file rows in `document_index`. Every document_index
            # row gets a `document_id` - duplicate content (previously chained
            # via `duplicate_of_id` to one specific file row) now instead shares
            # a `documents` row directly, so the group survives independently of
            # which physical row happens to represent it.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            if "document_id" not in columns:
                conn.execute(
                    "ALTER TABLE document_index "
                    "ADD COLUMN document_id INTEGER REFERENCES documents(id)"
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
            # `document_phases` (deeper OCR phases) was keyed by the physical row
            # holding a document's pages; it's now keyed by the logical document so
            # its progress survives that row changing. A group's phases were only
            # ever recorded against one row, so nothing collides on the way over.
            conn.execute("ALTER TABLE document_phases RENAME TO document_phases_old")
            conn.execute(
                """
                CREATE TABLE document_phases (
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    phase INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    indexed_at TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    peak_memory_mb REAL,
                    cpu_percent REAL,
                    PRIMARY KEY (document_id, phase)
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO document_phases "
                "(document_id, phase, started_at, completed_at, indexed_at, duration_seconds, "
                "peak_memory_mb, cpu_percent) "
                "SELECT d.document_id, p.phase, p.started_at, p.completed_at, p.indexed_at, "
                "p.duration_seconds, p.peak_memory_mb, p.cpu_percent "
                "FROM document_phases_old p JOIN document_index d ON d.id = p.document_id"
            )
            conn.execute("DROP TABLE document_phases_old")
            conn.execute("DROP TABLE document_index")
            conn.execute("ALTER TABLE document_index_new RENAME TO document_index")
            conn.execute("PRAGMA foreign_keys = ON")
        if from_version < 22:
            # `documents.file_path` is the primary path among a document's copies
            # (the earliest one that isn't 'removed'); NULL when none is left.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
            if "file_path" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN file_path TEXT")
            conn.execute(
                "UPDATE documents SET file_path = ("
                "SELECT file_path FROM document_index "
                "WHERE document_id = documents.id AND status != 'removed' "
                "ORDER BY id ASC LIMIT 1)"
            )
        if from_version < 23:
            # `checksum` already held a SHA-256 digest - renamed to `sha256` so the
            # column name says so, rather than changing what's stored in it.
            # `created_at`/`modified_at` are new: OS-level file creation/modification
            # timestamps captured at scan time, alongside (not replacing) `mtime`,
            # which the fast dirty-check in `_has_content_changed` still uses as-is.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            if "checksum" in columns and "sha256" not in columns:
                conn.execute("ALTER TABLE document_index RENAME COLUMN checksum TO sha256")
                conn.execute("DROP INDEX IF EXISTS idx_document_index_checksum")
            if "created_at" not in columns:
                conn.execute("ALTER TABLE document_index ADD COLUMN created_at TEXT")
            if "modified_at" not in columns:
                conn.execute("ALTER TABLE document_index ADD COLUMN modified_at TEXT")
        if from_version < 24:
            # Adds 'processing' to the status CHECK constraint, for a file that's
            # actively being worked on - previously `started_at` was set while
            # status stayed 'pending' for the whole run, with no way to tell "not
            # started yet" apart from "in flight" from the status column alone.
            # SQLite can't widen a CHECK constraint in place, so this follows the
            # same rebuild-the-table pattern as the earlier migrations.
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
                )
                """
            )
            conn.execute(
                "INSERT INTO document_index_new "
                "(id, source_id, document_id, file_path, file_type, status, error_message, "
                "indexed_at, started_at, completed_at, file_size_bytes, sha256, mtime, "
                "created_at, modified_at, removed_at, retry_count, peak_memory_mb, cpu_percent) "
                "SELECT id, source_id, document_id, file_path, file_type, status, error_message, "
                "indexed_at, started_at, completed_at, file_size_bytes, sha256, mtime, "
                "created_at, modified_at, removed_at, retry_count, peak_memory_mb, cpu_percent "
                "FROM document_index"
            )
            conn.execute("DROP TABLE document_index")
            conn.execute("ALTER TABLE document_index_new RENAME TO document_index")
            conn.execute("PRAGMA foreign_keys = ON")
        if from_version < 25:
            # `pdf_pages_fts`/`image_pages_fts` were just created (empty) by `Db._SCHEMA`,
            # which runs unconditionally before this migration - pages written before
            # this version never fired their INSERT triggers, so index them in one go.
            # 'rebuild' (unlike a plain INSERT ... SELECT) is idempotent, so it's safe
            # even if an index was already populated.
            conn.execute("INSERT INTO pdf_pages_fts(pdf_pages_fts) VALUES ('rebuild')")
            conn.execute("INSERT INTO image_pages_fts(image_pages_fts) VALUES ('rebuild')")
        if from_version < 26:
            # Adds 'txt' to the file_type CHECK constraints (plain-text support, stored
            # in `text_pages`, which `Db._SCHEMA` just created). SQLite can't widen a
            # CHECK in place, so these three tables follow the same rebuild-the-table
            # pattern as the earlier migrations.
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                CREATE TABLE document_index_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES sources(id),
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    file_path TEXT NOT NULL UNIQUE,
                    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'txt')),
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
                )
                """
            )
            conn.execute("INSERT INTO document_index_new SELECT * FROM document_index")
            conn.execute("DROP TABLE document_index")
            conn.execute("ALTER TABLE document_index_new RENAME TO document_index")

            conn.execute(
                """
                CREATE TABLE processing_metrics_new (
                    phase INTEGER NOT NULL DEFAULT 1,
                    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'txt')),
                    size_bucket TEXT NOT NULL CHECK (size_bucket IN ('small', 'medium', 'large')),
                    document_count INTEGER NOT NULL DEFAULT 0,
                    avg_duration_seconds REAL NOT NULL DEFAULT 0,
                    avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
                    avg_cpu_percent REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (phase, file_type, size_bucket)
                )
                """
            )
            conn.execute("INSERT INTO processing_metrics_new SELECT * FROM processing_metrics")
            conn.execute("DROP TABLE processing_metrics")
            conn.execute("ALTER TABLE processing_metrics_new RENAME TO processing_metrics")

            conn.execute(
                """
                CREATE TABLE confidence_metrics_new (
                    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'txt')),
                    process_type TEXT NOT NULL CHECK (process_type IN ('native', 'ocr', 'mixed')),
                    page_count INTEGER NOT NULL DEFAULT 0,
                    avg_confidence REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (file_type, process_type)
                )
                """
            )
            conn.execute("INSERT INTO confidence_metrics_new SELECT * FROM confidence_metrics")
            conn.execute("DROP TABLE confidence_metrics")
            conn.execute("ALTER TABLE confidence_metrics_new RENAME TO confidence_metrics")
            conn.execute("PRAGMA foreign_keys = ON")
