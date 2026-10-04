"""Schema migrations for VethuQ's local SQLite database."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from vethuq_core.db.queries.documents import Document
from vethuq_core.paths.extensions import Extensions


class Migration:
    @staticmethod
    def _lacks_document_identity(conn: sqlite3.Connection) -> bool:
        """Return whether `document_index` still predates logical document identity."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        return "document_id" not in columns or "duplicate_of_id" in columns

    @staticmethod
    def schema(conn: sqlite3.Connection, *, from_version: int) -> None:
        if from_version < 28:
            # Before v28 the trigram indexes were named `<table>_fts`; they are now
            # `<table>_trigram`, next to the word indexes `<table>_words`. Drop the old
            # ones, if any (rebuilt below under the new names).
            #
            # `Db._SCHEMA` just created the new indexes and triggers, but the indexes are
            # still empty until the v28 step below rebuilds them. Until then an earlier
            # step updating `pdf_pages`/`image_pages` rows (the v27 `char_count` backfill)
            # would fire their UPDATE trigger, which 'delete's entries that were never
            # indexed and corrupts the index. Drop the new triggers here too; `Db`
            # restores them afterwards.
            for table in ("pdf_pages", "image_pages"):
                for suffix in ("ai", "ad", "au"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {table}_fts_{suffix}")
                    conn.execute(f"DROP TRIGGER IF EXISTS {table}_trigram_{suffix}")
                    conn.execute(f"DROP TRIGGER IF EXISTS {table}_words_{suffix}")
                conn.execute(f"DROP TABLE IF EXISTS {table}_fts")
        if from_version < 30:
            # `Db._SCHEMA` just created the indexes over derived text (`noise_text`,
            # `norm_text`) and their triggers, but the columns they read are only added (and
            # backfilled) by the v29 and v30 steps below, so the triggers must not fire before
            # then. The UPDATE triggers of the older indexes go too: the backfill would
            # otherwise re-index every page's text for nothing. `Db` restores all of them
            # afterwards.
            for table in ("pdf_pages", "image_pages"):
                for kind in ("noise", "norm"):
                    for suffix in ("ai", "ad", "au"):
                        conn.execute(f"DROP TRIGGER IF EXISTS {table}_{kind}_{suffix}")
                for kind in ("trigram", "words"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {table}_{kind}_au")
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
            # `CREATE TABLE IF NOT EXISTS` in `_SCHEMA` before migrations run. Its rows have
            # no extension yet; the v30 step below rebuilds the table per extension anyway.
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO confidence_metrics "
                "(file_type, extension, process_type, page_count, avg_confidence, updated_at) "
                "SELECT 'pdf', '', source, COUNT(*), AVG(confidence), ? "
                "FROM pdf_pages GROUP BY source",
                (now,),
            )
            conn.execute(
                "INSERT INTO confidence_metrics "
                "(file_type, extension, process_type, page_count, avg_confidence, updated_at) "
                "SELECT 'image', '', 'ocr', COUNT(*), AVG(confidence), ? "
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
        if from_version < 26:
            # Adds 'unsupported' to the file_type and status CHECK constraints, so files with no
            # registered reader (.txt, .csv, ...) can be recorded with an error
            # instead of being invisible. Same rebuild-the-table pattern as above,
            # since SQLite can't widen a CHECK constraint in place.
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                CREATE TABLE document_index_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES sources(id),
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    file_path TEXT NOT NULL UNIQUE,
                    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'unsupported')),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending', 'processing', 'indexed', 'error', 'removed', 'unsupported'
                        )),
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

        if from_version < 27:
            # `char_count` (len of `ocr_text`) is recorded at write time so it's
            # queryable without re-reading the text; pages written before this
            # version need a one-off backfill.
            for table in ("pdf_pages", "image_pages"):
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if "char_count" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN char_count INTEGER NOT NULL DEFAULT 0"
                    )
                conn.execute(f"UPDATE {table} SET char_count = LENGTH(ocr_text)")

        if from_version < 28:
            # The trigram and word indexes were just created (empty) by `Db._SCHEMA`, and
            # pages written before this version never fired their INSERT triggers.
            # 'rebuild' re-reads every row from the content table; unlike a plain
            # INSERT ... SELECT it is idempotent. This also covers databases that predate
            # the trigram indexes (v25).
            for index in Document.TEXT_SEARCH_INDEXES:
                Document.rebuild_search_index(conn, index)

        if from_version < 29:
            # Each page's text now also has a noise-free, look-alike-folded skeleton recorded
            # next to it (`noise_text`), with its own trigram index, for the `noise-fuzzy`
            # search. Pages written before this version get theirs now.
            for table in Document.PAGE_TABLES:
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if "noise_text" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN noise_text TEXT NOT NULL DEFAULT ''"
                    )
                Document.refresh_derived_text(conn, table, ("noise",))
            for index in Document.SEARCH_INDEXES:
                if index.endswith("_noise"):
                    Document.rebuild_search_index(conn, index)

        if from_version < 30:
            # Each page also records its text folded as coarsely as any search level does
            # (`norm_text`, with its own trigram index) so the engines that normalize can find
            # candidate pages through SQLite; and the skeleton (`noise_text`) now folds Unicode
            # too, so it is brought up to date. Both are rebuilt here.
            for table in Document.PAGE_TABLES:
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if "norm_text" not in columns:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN norm_text TEXT NOT NULL DEFAULT ''"
                    )
                Document.refresh_derived_text(conn, table)
            for index in Document.DERIVED_SEARCH_INDEXES:
                Document.rebuild_search_index(conn, index)

        if from_version < 29:
            # `reindex_pending` marks a file a full re-index has queued: it keeps its status
            # (and so its searchable pages) until it is reprocessed, instead of being reset
            # to 'pending'.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            if "reindex_pending" not in columns:
                conn.execute(
                    "ALTER TABLE document_index "
                    "ADD COLUMN reindex_pending INTEGER NOT NULL DEFAULT 0"
                )

        if from_version < 30:
            Migration._track_metrics_per_extension(conn)

    @staticmethod
    def _track_metrics_per_extension(conn: sqlite3.Connection) -> None:
        """Rebuild `processing_metrics` and `confidence_metrics` keyed by file extension.

        They used to average every image together under `image`, blending PNG and JPG. The
        old running averages can't be split after the fact, so both tables are rebuilt from
        what is stored: each indexed document's timings (and deeper-phase work) and each
        stored page's confidence, grouped by the extension of the file's path. History for
        files that have since been removed is not recoverable and drops out of the averages.
        """
        conn.execute("DROP TABLE processing_metrics")
        conn.execute("DROP TABLE confidence_metrics")
        conn.execute(
            """
            CREATE TABLE processing_metrics (
                phase INTEGER NOT NULL DEFAULT 1,
                file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
                extension TEXT NOT NULL,
                size_bucket TEXT NOT NULL CHECK (size_bucket IN ('small', 'medium', 'large')),
                document_count INTEGER NOT NULL DEFAULT 0,
                avg_duration_seconds REAL NOT NULL DEFAULT 0,
                avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
                avg_cpu_percent REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (phase, file_type, extension, size_bucket)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE confidence_metrics (
                file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
                extension TEXT NOT NULL,
                process_type TEXT NOT NULL CHECK (process_type IN ('native', 'ocr', 'mixed')),
                page_count INTEGER NOT NULL DEFAULT 0,
                avg_confidence REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (file_type, extension, process_type)
            )
            """
        )
        now = datetime.now(UTC).isoformat()

        # A document is "carried" by the row that holds its pages; duplicates have none, and
        # were never OCR'd, so they contributed nothing to the old averages either.
        carries_pages = (
            "(EXISTS (SELECT 1 FROM pdf_pages WHERE document_id = {t}.id) "
            "OR EXISTS (SELECT 1 FROM image_pages WHERE document_id = {t}.id))"
        )

        # (phase, file_type, extension, size_bucket) -> [documents, duration, memory, cpu]
        processing: dict[tuple[int, str, str, str], list[float]] = {}

        def fold(phase, file_type, path, size, duration, memory, cpu) -> None:
            # Keep these thresholds in sync with `Metrics.size_bucket`.
            size = size or 0
            bucket = "small" if size < 500_000 else "medium" if size < 3_000_000 else "large"
            key = (phase, file_type, Extensions.of(path), bucket)
            totals = processing.setdefault(key, [0, 0.0, 0.0, 0.0])
            totals[0] += 1
            totals[1] += duration
            totals[2] += memory or 0.0
            totals[3] += cpu or 0.0

        for row in conn.execute(
            "SELECT di.file_path, di.file_type, di.file_size_bytes, di.started_at, "
            "di.completed_at, di.peak_memory_mb, di.cpu_percent FROM document_index di "
            "WHERE di.status = 'indexed' AND di.file_type IN ('pdf', 'image') "
            "AND di.started_at IS NOT NULL AND di.completed_at IS NOT NULL AND "
            + carries_pages.format(t="di")
        ):
            duration = (
                datetime.fromisoformat(row["completed_at"])
                - datetime.fromisoformat(row["started_at"])
            ).total_seconds()
            fold(
                1,
                row["file_type"],
                row["file_path"],
                row["file_size_bytes"],
                duration,
                row["peak_memory_mb"],
                row["cpu_percent"],
            )

        for row in conn.execute(
            "SELECT dp.phase, dp.duration_seconds, dp.peak_memory_mb, dp.cpu_percent, "
            "di.file_path, di.file_type, di.file_size_bytes FROM document_phases dp "
            "JOIN document_index di ON di.id = ("
            "  SELECT MIN(c.id) FROM document_index c WHERE c.document_id = dp.document_id "
            "  AND c.status = 'indexed' AND c.file_type IN ('pdf', 'image') AND "
            + carries_pages.format(t="c")
            + ") WHERE dp.completed_at IS NOT NULL AND dp.duration_seconds > 0"
        ):
            fold(
                row["phase"],
                row["file_type"],
                row["file_path"],
                row["file_size_bytes"],
                row["duration_seconds"],
                row["peak_memory_mb"],
                row["cpu_percent"],
            )

        conn.executemany(
            "INSERT INTO processing_metrics (phase, file_type, extension, size_bucket, "
            "document_count, avg_duration_seconds, avg_peak_memory_mb, avg_cpu_percent, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (phase, file_type, extension, bucket, int(n), t / n, m / n, c / n, now)
                for (phase, file_type, extension, bucket), (n, t, m, c) in processing.items()
            ],
        )

        # (file_type, extension, process_type) -> [pages, confidence sum]
        confidence: dict[tuple[str, str, str], list[float]] = {}
        for table, process_type_sql in (("pdf_pages", "p.source"), ("image_pages", "'ocr'")):
            for row in conn.execute(
                f"SELECT di.file_path, di.file_type, {process_type_sql} AS process_type, "
                f"COUNT(*) AS pages, SUM(p.confidence) AS total FROM {table} p "
                f"JOIN document_index di ON di.id = p.document_id "
                f"GROUP BY di.id, {process_type_sql}"
            ):
                key = (row["file_type"], Extensions.of(row["file_path"]), row["process_type"])
                totals = confidence.setdefault(key, [0, 0.0])
                totals[0] += row["pages"]
                totals[1] += row["total"]
        conn.executemany(
            "INSERT INTO confidence_metrics (file_type, extension, process_type, page_count, "
            "avg_confidence, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (file_type, extension, process_type, int(n), total / n, now)
                for (file_type, extension, process_type), (n, total) in confidence.items()
            ],
        )
