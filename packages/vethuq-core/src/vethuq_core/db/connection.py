"""SQLite connection and schema bootstrap for VethuQ's local data store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from vethuq_core.db.migration import Migration
from vethuq_core.db.queries.documents import Document
from vethuq_core.db.queries.semantic import Semantic
from vethuq_core.errors import CorruptDatabaseError, SchemaVersionError
from vethuq_core.logs import Logs
from vethuq_core.paths import Paths

_logger = Logs.get_logger("database")


class Db:
    APP_NAME = Paths.APP_NAME
    DB_FILENAME = Paths.DB_FILENAME

    # How long a writer waits on a lock held by another connection (WAL still
    # serializes writers against each other) before raising "database is locked" -
    # generous enough to ride out a concurrent writer's transaction (e.g. the
    # desktop app's background indexing overlapping a CLI command against the
    # same database) rather than failing immediately.
    BUSY_TIMEOUT_MS = 5000

    SCHEMA_VERSION = 34

    _SCHEMA = (
        """
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
    removed_at TEXT,
    languages TEXT
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
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image', 'unsupported')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'indexed', 'error', 'removed', 'unsupported')),
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
    cpu_percent REAL,
    reindex_pending INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pdf_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    page_number INTEGER NOT NULL,
    ocr_text TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    noise_text TEXT NOT NULL DEFAULT '',
    norm_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'ocr' CHECK (source IN ('native', 'ocr', 'mixed')),
    ocr_engine TEXT,
    language TEXT,
    image_width INTEGER,
    image_height INTEGER,
    ocr_phase INTEGER NOT NULL DEFAULT 1,
    ocr_angles TEXT NOT NULL DEFAULT '0',
    ocr_langs TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS image_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document_index(id),
    ocr_text TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    noise_text TEXT NOT NULL DEFAULT '',
    norm_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL,
    ocr_engine TEXT,
    language TEXT,
    image_width INTEGER,
    image_height INTEGER,
    ocr_phase INTEGER NOT NULL DEFAULT 1,
    ocr_angles TEXT NOT NULL DEFAULT '0',
    ocr_langs TEXT NOT NULL DEFAULT ''
);

-- The OCR passes a file gets, one row per (file, language), in the order they run: the
-- language the pass reads, whether it was chosen by default, by detection or by the user, and
-- how the pass went. `document_id` is the `document_index` row that carries the pages, like
-- `pdf_pages.document_id`.
CREATE TABLE IF NOT EXISTS document_languages (
    document_id INTEGER NOT NULL REFERENCES document_index(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'error', 'skipped')),
    source TEXT NOT NULL DEFAULT 'default' CHECK (source IN ('default', 'auto', 'manual')),
    confidence REAL,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    PRIMARY KEY (document_id, language)
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
    extension TEXT NOT NULL,
    size_bucket TEXT NOT NULL CHECK (size_bucket IN ('small', 'medium', 'large')),
    document_count INTEGER NOT NULL DEFAULT 0,
    avg_duration_seconds REAL NOT NULL DEFAULT 0,
    avg_peak_memory_mb REAL NOT NULL DEFAULT 0,
    avg_cpu_percent REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    -- The OCR language the time was spent reading; each language keeps its own averages.
    language TEXT NOT NULL DEFAULT 'en',
    PRIMARY KEY (phase, language, file_type, extension, size_bucket)
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
    extension TEXT NOT NULL,
    process_type TEXT NOT NULL CHECK (process_type IN ('native', 'ocr', 'mixed')),
    page_count INTEGER NOT NULL DEFAULT 0,
    avg_confidence REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    PRIMARY KEY (file_type, extension, process_type, language)
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
CREATE VIRTUAL TABLE IF NOT EXISTS pdf_pages_trigram USING fts5(
    ocr_text,
    content='pdf_pages',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS pdf_pages_trigram_ai AFTER INSERT ON pdf_pages BEGIN
    INSERT INTO pdf_pages_trigram(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_pages_trigram_ad AFTER DELETE ON pdf_pages BEGIN
    INSERT INTO pdf_pages_trigram(pdf_pages_trigram, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_pages_trigram_au AFTER UPDATE ON pdf_pages BEGIN
    INSERT INTO pdf_pages_trigram(pdf_pages_trigram, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
    INSERT INTO pdf_pages_trigram(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS image_pages_trigram USING fts5(
    ocr_text,
    content='image_pages',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS image_pages_trigram_ai AFTER INSERT ON image_pages BEGIN
    INSERT INTO image_pages_trigram(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS image_pages_trigram_ad AFTER DELETE ON image_pages BEGIN
    INSERT INTO image_pages_trigram(image_pages_trigram, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS image_pages_trigram_au AFTER UPDATE ON image_pages BEGIN
    INSERT INTO image_pages_trigram(image_pages_trigram, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
    INSERT INTO image_pages_trigram(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

-- Word-based full-text index over ocr_text, one per pages table, backing the
-- `full-text` search engine (the trigram indexes above can't rank or match
-- whole words). `unicode61` splits on words and folds case, `remove_diacritics
-- 2` folds accents ("cafe" finds "café"), and `porter` stems English words
-- ("invoices" finds "invoice"); the same tokenizer runs over the query, so
-- text in other languages still matches itself. External-content tables kept
-- in sync by triggers, exactly like the trigram ones.

CREATE VIRTUAL TABLE IF NOT EXISTS pdf_pages_words USING fts5(
    ocr_text,
    content='pdf_pages',
    content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS pdf_pages_words_ai AFTER INSERT ON pdf_pages BEGIN
    INSERT INTO pdf_pages_words(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_pages_words_ad AFTER DELETE ON pdf_pages BEGIN
    INSERT INTO pdf_pages_words(pdf_pages_words, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS pdf_pages_words_au AFTER UPDATE ON pdf_pages BEGIN
    INSERT INTO pdf_pages_words(pdf_pages_words, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
    INSERT INTO pdf_pages_words(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS image_pages_words USING fts5(
    ocr_text,
    content='image_pages',
    content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS image_pages_words_ai AFTER INSERT ON image_pages BEGIN
    INSERT INTO image_pages_words(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS image_pages_words_ad AFTER DELETE ON image_pages BEGIN
    INSERT INTO image_pages_words(image_pages_words, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS image_pages_words_au AFTER UPDATE ON image_pages BEGIN
    INSERT INTO image_pages_words(image_pages_words, rowid, ocr_text)
        VALUES ('delete', old.id, old.ocr_text);
    INSERT INTO image_pages_words(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;
"""
        + Document.derived_schema()
        + Semantic.schema()
    )

    @staticmethod
    def _migrate_legacy_db(root: Path, db_dir: Path) -> None:
        """Move a database left directly in the data root by an older version into `db/`."""
        legacy = root / Db.DB_FILENAME
        target = db_dir / Db.DB_FILENAME
        if not legacy.exists() or target.exists():
            return
        for suffix in ("", "-wal", "-shm"):
            src = root / (Db.DB_FILENAME + suffix)
            if src.exists():
                src.replace(db_dir / (Db.DB_FILENAME + suffix))

    @staticmethod
    def default_db_path() -> Path:
        """Return the per-user path where VethuQ's SQLite database lives (`<data root>/db/`)."""
        Paths.check_config()
        root = Paths.default_data_root()
        db_dir = root / Paths.DB_DIRNAME
        Paths.ensure_writable(db_dir)
        Db._migrate_legacy_db(root, db_dir)
        return db_dir / Db.DB_FILENAME

    @staticmethod
    def _corruption_error(exc: sqlite3.Error, db_path: Path) -> CorruptDatabaseError | None:
        """A `CorruptDatabaseError` if `exc` means the file is damaged, else None.

        SQLite reports "file is not a database" and "database disk image is malformed"
        as a plain `DatabaseError`; its subclasses (locked, read-only, ...) are not corruption.
        """
        if type(exc) is not sqlite3.DatabaseError:
            return None
        _logger.error("Database file is corrupt or not a database: path=%s (%s)", db_path, exc)
        return CorruptDatabaseError(
            f"The VethuQ database at {db_path} is damaged or isn't a database ({exc}).",
            "Restore a backup with 'vethuq db restore <name>' (see 'vethuq db backup list'), "
            "or move the file aside to start fresh.",
        )

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
        Logs.setup("database", path)
        try:
            conn = sqlite3.connect(path, check_same_thread=check_same_thread)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(f"PRAGMA busy_timeout = {Db.BUSY_TIMEOUT_MS}")
        except sqlite3.Error as exc:
            _logger.exception("Could not open database: path=%s", path)
            corrupt = Db._corruption_error(exc, path)
            if corrupt is not None:
                raise corrupt from exc
            raise
        try:
            Db._ensure_schema(conn, path)
        except BaseException as exc:
            if isinstance(exc, sqlite3.Error):
                _logger.exception("Could not prepare database schema: path=%s", path)
            conn.close()
            if isinstance(exc, sqlite3.Error):
                corrupt = Db._corruption_error(exc, path)
                if corrupt is not None:
                    raise corrupt from exc
            raise

        from vethuq_core.db.backup import Backup
        from vethuq_core.db.integrity import IntegrityCheck
        from vethuq_core.sources import Sources
        from vethuq_core.storage.sqlite import SqliteStorage

        storage = SqliteStorage(conn)
        Sources.purge_expired_sources(storage)
        Sources.purge_expired_documents(storage)
        IntegrityCheck.maybe_run(storage)
        Backup.maybe_run_auto(storage, path)
        return conn

    @staticmethod
    def _backup_before_migration(conn: sqlite3.Connection, db_path: Path) -> None:
        """Back up the pre-migration database as a `safety-premigration-...` backup.

        Goes through the regular backup system (compressed, in the backups folder,
        pruned with the other automatic backups) and SQLite's own backup API on the
        already-open connection, so the copy is consistent even though - under WAL -
        some already-committed data may currently live only in the `-wal` file. Runs
        before `Migration.schema` so a failed or bad migration can be rolled back to it.
        """
        from vethuq_core.db.backup import Backup

        _logger.info("Backing up database before migration")
        Backup.create(
            db_path, prefix=f"{Backup.SAFETY_PREFIX}premigration-", require_ok=False, conn=conn
        )

    @staticmethod
    def _check_schema_not_newer(conn: sqlite3.Connection) -> None:
        """Refuse to run against a database written by a newer VethuQ.

        Runs before `_SCHEMA` so an older build never touches (or creates tables
        in) a database whose schema it doesn't fully understand.
        """
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        if has_table is None:
            return
        row = conn.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
        if row["version"] is not None and row["version"] > Db.SCHEMA_VERSION:
            _logger.error(
                "Refusing to open database: schema v%d is newer than supported v%d",
                row["version"],
                Db.SCHEMA_VERSION,
            )
            raise SchemaVersionError(
                f"The database schema (version {row['version']}) is newer than this version "
                f"of VethuQ supports (version {Db.SCHEMA_VERSION}).",
                "Upgrade VethuQ to open this database.",
            )

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection, db_path: Path) -> None:
        Db._check_schema_not_newer(conn)
        conn.executescript(Db._SCHEMA)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            _logger.info("Created database schema v%d at %s", Db.SCHEMA_VERSION, db_path)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (Db.SCHEMA_VERSION,))
        elif row["version"] < Db.SCHEMA_VERSION:
            _logger.info(
                "Migrating database schema from v%d to v%d", row["version"], Db.SCHEMA_VERSION
            )
            Db._backup_before_migration(conn, db_path)
            Migration.schema(conn, from_version=row["version"])
            if row["version"] < 31:
                # Restores the index triggers `Migration.schema` dropped while it
                # backfilled the (then still empty) indexes - idempotent.
                conn.executescript(Db._SCHEMA)
            conn.execute("UPDATE schema_version SET version = ?", (Db.SCHEMA_VERSION,))
        # The word indexes for scripts whose marks are part of the word: created here, after
        # the tables and migrations, because whether they can exist depends on this SQLite.
        if not Document.ensure_complex_word_indexes(conn):
            _logger.warning(
                "This SQLite (%s) cannot build the word index Telugu full-text search needs; "
                "full-text and proximity search will not find Telugu words",
                sqlite3.sqlite_version,
            )
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
