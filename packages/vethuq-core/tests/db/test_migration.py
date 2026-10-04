import sqlite3

from vethuq_core.db import Db


class TestMigration:
    def test_connect_migrates_index_runs_missing_mode_column(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: an
        # index_runs table that predates the "mode" column, at schema version 5.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (5);
            CREATE TABLE index_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                pid INTEGER,
                total_files INTEGER NOT NULL DEFAULT 0,
                processed_files INTEGER NOT NULL DEFAULT 0,
                failed_files INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );
            """
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(index_runs)")}
            assert "mode" in columns

            # The new column must be usable without specifying it explicitly,
            # matching what a pre-existing INSERT statement written before this
            # migration would still run.
            conn.execute(
                "INSERT INTO index_runs (target, status, pid, total_files, started_at) "
                "VALUES (NULL, 'running', 1, 1, '2026-01-01T00:00:00+00:00')"
            )
            conn.commit()
            row = conn.execute("SELECT mode FROM index_runs").fetchone()
            assert row["mode"] == "run"

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_migrates_document_index_missing_file_size_column(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: a
        # document_index table that predates the "file_size_bytes" column, at
        # schema version 6.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (6);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                indexed_at TEXT,
                started_at TEXT,
                completed_at TEXT
            );
            """
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            assert "file_size_bytes" in columns

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_migrates_document_index_missing_checksum_columns(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: a
        # document_index table that predates the "checksum"/"duplicate_of_id"
        # columns, at schema version 8.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (8);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                indexed_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                file_size_bytes INTEGER
            );
            """
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            # Renamed to "sha256" by the version-18 migration, which also runs here
            # since this simulated database starts well before it.
            assert "sha256" in columns
            assert "checksum" not in columns
            assert "document_id" in columns
            assert "duplicate_of_id" not in columns

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_migrates_document_index_missing_mtime_column(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: a
        # document_index table that predates the "mtime" column, at schema
        # version 9.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (9);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                indexed_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                file_size_bytes INTEGER,
                checksum TEXT,
                duplicate_of_id INTEGER REFERENCES document_index(id)
            );
            """
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            assert "mtime" in columns

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_migrates_document_index_status_check_and_removed_at(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: a
        # document_index table that predates the "removed_at" column and the
        # wider 'removed' status value, at schema version 10.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (10);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'indexed', 'error')),
                error_message TEXT,
                indexed_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                file_size_bytes INTEGER,
                checksum TEXT,
                duplicate_of_id INTEGER REFERENCES document_index(id),
                mtime REAL
            );
            """
        )
        old_conn.execute(
            "INSERT INTO sources (id, path, source_type, status, added_at) "
            "VALUES (1, 'C:/docs', 'folder', 'indexed', '2026-01-01T00:00:00')"
        )
        old_conn.execute(
            "INSERT INTO document_index (id, source_id, file_path, file_type, status) "
            "VALUES (1, 1, 'C:/docs/a.png', 'image', 'indexed')"
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            assert "removed_at" in columns

            # The pre-existing row survives the table rebuild with its data intact.
            row = conn.execute("SELECT * FROM document_index WHERE id = 1").fetchone()
            assert row["file_path"] == "C:/docs/a.png"
            assert row["status"] == "indexed"

            # The widened CHECK constraint now accepts 'removed'.
            conn.execute("UPDATE document_index SET status = 'removed' WHERE id = 1")
            conn.commit()

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_migrates_processing_metrics_confidence_split(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: a
        # processing_metrics table that blends avg_confidence and page counts
        # across process types, at schema version 14, with page-level history
        # still intact in pdf_pages/image_pages.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (14);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
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
            CREATE TABLE pdf_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES document_index(id),
                page_number INTEGER NOT NULL,
                ocr_text TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'ocr'
            );
            CREATE TABLE image_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES document_index(id),
                ocr_text TEXT NOT NULL,
                confidence REAL NOT NULL
            );
            CREATE TABLE processing_metrics (
                file_type TEXT PRIMARY KEY,
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
            INSERT INTO sources (id, path, source_type, added_at)
                VALUES (1, '/x', 'folder', '2026-01-01T00:00:00+00:00');
            INSERT INTO document_index (id, source_id, file_path, file_type) VALUES
                (1, 1, '/x/a.pdf', 'pdf'),
                (2, 1, '/x/b.png', 'image');
            INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source) VALUES
                (1, 1, 'text', 1.0, 'native'),
                (1, 2, 'text', 0.6, 'ocr'),
                (1, 3, 'text', 0.8, 'mixed');
            INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES
                (2, 'text', 0.7);
            INSERT INTO processing_metrics
                (file_type, document_count, avg_duration_seconds, avg_confidence,
                 pages_native, pages_ocr, pages_mixed, avg_peak_memory_mb,
                 avg_cpu_percent, updated_at)
            VALUES
                ('pdf', 1, 5.0, 0.8, 1, 1, 1, 100.0, 10.0, '2026-01-01T00:00:00+00:00'),
                ('image', 1, 2.0, 0.7, 0, 1, 0, 50.0, 5.0, '2026-01-01T00:00:00+00:00');
            """
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
            assert "avg_confidence" not in columns
            assert "pages_native" not in columns

            # Timings can't be recovered for documents that were never indexed, so the
            # rebuilt table starts empty (see `test_stats_per_extension_migration.py`).
            assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None

            confidence_rows = {
                (row["extension"], row["process_type"]): (row["page_count"], row["avg_confidence"])
                for row in conn.execute(
                    "SELECT extension, process_type, page_count, avg_confidence "
                    "FROM confidence_metrics"
                )
            }
            assert confidence_rows[("pdf", "native")] == (1, 1.0)
            assert confidence_rows[("pdf", "ocr")] == (1, 0.6)
            assert confidence_rows[("pdf", "mixed")] == (1, 0.8)
            assert confidence_rows[("png", "ocr")] == (1, 0.7)

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_migrates_document_index_checksum_to_sha256_and_adds_timestamps(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: a
        # document_index table with the "checksum" column (already a SHA-256
        # digest, just not named for it) and no created_at/modified_at columns,
        # at schema version 17.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (17);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                document_id INTEGER NOT NULL REFERENCES documents(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
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
            CREATE INDEX idx_document_index_checksum ON document_index(checksum);
            """
        )
        old_conn.execute(
            "INSERT INTO sources (id, path, source_type, status, added_at) "
            "VALUES (1, '/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00')"
        )
        old_conn.execute(
            "INSERT INTO documents (id, created_at) VALUES (1, '2026-01-01T00:00:00+00:00')"
        )
        old_conn.execute(
            "INSERT INTO document_index "
            "(id, source_id, document_id, file_path, file_type, status, checksum, mtime) "
            "VALUES (1, 1, 1, '/docs/a.pdf', 'pdf', 'indexed', 'abc123', 100.0)"
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
            assert "sha256" in columns
            assert "checksum" not in columns
            assert "created_at" in columns
            assert "modified_at" in columns

            # The pre-existing row's data survives the rename, under its new name.
            row = conn.execute("SELECT * FROM document_index WHERE id = 1").fetchone()
            assert row["sha256"] == "abc123"
            assert row["created_at"] is None
            assert row["modified_at"] is None

            indexes = {row["name"] for row in conn.execute("PRAGMA index_list(document_index)")}
            assert "idx_document_index_sha256" in indexes
            assert "idx_document_index_checksum" not in indexes

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_migrates_document_index_status_check_allows_processing(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code: a
        # document_index table whose status CHECK constraint doesn't yet allow
        # 'processing', at schema version 23.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (23);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                document_id INTEGER NOT NULL REFERENCES documents(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'indexed', 'error', 'removed')),
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
            CREATE INDEX idx_document_index_sha256 ON document_index(sha256);
            """
        )
        old_conn.execute(
            "INSERT INTO sources (id, path, source_type, status, added_at) "
            "VALUES (1, '/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00')"
        )
        old_conn.execute(
            "INSERT INTO documents (id, created_at) VALUES (1, '2026-01-01T00:00:00+00:00')"
        )
        old_conn.execute(
            "INSERT INTO document_index "
            "(id, source_id, document_id, file_path, file_type, status, sha256, mtime) "
            "VALUES (1, 1, 1, '/docs/a.pdf', 'pdf', 'indexed', 'abc123', 100.0)"
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            # The pre-existing row survives the rebuild.
            row = conn.execute("SELECT * FROM document_index WHERE id = 1").fetchone()
            assert row["status"] == "indexed"
            assert row["sha256"] == "abc123"

            # 'processing' is now an allowed status - previously the CHECK
            # constraint would reject it.
            conn.execute(
                "INSERT INTO document_index "
                "(source_id, document_id, file_path, file_type, status, started_at) "
                "VALUES (1, 1, '/docs/b.pdf', 'pdf', 'processing', '2026-01-01T00:00:00+00:00')"
            )
            conn.commit()
            new_row = conn.execute(
                "SELECT status FROM document_index WHERE file_path = '/docs/b.pdf'"
            ).fetchone()
            assert new_row["status"] == "processing"

            indexes = {row["name"] for row in conn.execute("PRAGMA index_list(document_index)")}
            assert "idx_document_index_sha256" in indexes

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_backfills_fts_index_for_pre_existing_pages(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a database created by an older version of this code, at schema
        # version 24 - before pdf_pages_trigram/image_pages_trigram existed - with OCR
        # pages already written. Their INSERT triggers never fired for these rows
        # (the triggers didn't exist yet), so connect() must backfill them.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (24);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                document_id INTEGER NOT NULL REFERENCES documents(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
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
            CREATE TABLE pdf_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES document_index(id),
                page_number INTEGER NOT NULL,
                ocr_text TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'ocr',
                ocr_engine TEXT,
                language TEXT,
                image_width INTEGER,
                image_height INTEGER
            );
            CREATE TABLE image_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES document_index(id),
                ocr_text TEXT NOT NULL,
                confidence REAL NOT NULL,
                ocr_engine TEXT,
                language TEXT,
                image_width INTEGER,
                image_height INTEGER
            );
            """
        )
        old_conn.execute(
            "INSERT INTO sources (id, path, source_type, status, added_at) "
            "VALUES (1, '/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00')"
        )
        old_conn.execute(
            "INSERT INTO documents (id, created_at) VALUES (1, '2026-01-01T00:00:00+00:00')"
        )
        old_conn.execute(
            "INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status) "
            "VALUES (1, 1, 1, '/docs/a.pdf', 'pdf', 'indexed')"
        )
        old_conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (1, 1, 'a legacy page about large invoices', 0.9)"
        )
        old_conn.execute(
            "INSERT INTO documents (id, created_at) VALUES (2, '2026-01-01T00:00:00+00:00')"
        )
        old_conn.execute(
            "INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status) "
            "VALUES (2, 1, 2, '/docs/b.png', 'image', 'indexed')"
        )
        old_conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence) "
            "VALUES (2, 'a legacy scan of a signature', 0.9)"
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            pdf_hit = conn.execute(
                "SELECT rowid FROM pdf_pages_trigram WHERE ocr_text LIKE '%arge invoi%'"
            ).fetchone()
            assert pdf_hit is not None

            image_hit = conn.execute(
                "SELECT rowid FROM image_pages_trigram WHERE ocr_text LIKE '%signature%'"
            ).fetchone()
            assert image_hit is not None

            # The word-based index (added at v28) is rebuilt too, and its sync
            # triggers are back after the migration - a new page must be indexed.
            assert conn.execute(
                "SELECT rowid FROM pdf_pages_words WHERE pdf_pages_words MATCH '\"invoice\"'"
            ).fetchone()
            assert conn.execute(
                "SELECT rowid FROM image_pages_words WHERE image_pages_words MATCH '\"signature\"'"
            ).fetchone()
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (1, 2, 'a brand new receipt', 0.9)"
            )
            assert conn.execute(
                "SELECT rowid FROM pdf_pages_words WHERE pdf_pages_words MATCH '\"receipt\"'"
            ).fetchone()
            conn.execute("INSERT INTO pdf_pages_words(pdf_pages_words) VALUES ('integrity-check')")

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_renames_legacy_fts_indexes_to_trigram_and_words(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        conn = Db.connect(db_path)
        conn.execute(
            "INSERT INTO sources (path, source_type, status, added_at) "
            "VALUES ('/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute("INSERT INTO documents (created_at) VALUES ('2026-01-01T00:00:00+00:00')")
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (1, 1, '/docs/a.pdf', 'pdf', 'indexed')"
        )
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (1, 1, 'a large invoice', 0.9)"
        )
        conn.commit()
        # Rewind to a v27 database: trigram index under its old `_fts` name, no word index.
        for suffix in ("ai", "ad", "au"):
            conn.execute(f"DROP TRIGGER pdf_pages_trigram_{suffix}")
            conn.execute(f"DROP TRIGGER pdf_pages_words_{suffix}")
        conn.execute("DROP TABLE pdf_pages_trigram")
        conn.execute("DROP TABLE pdf_pages_words")
        conn.execute(
            "CREATE VIRTUAL TABLE pdf_pages_fts USING fts5("
            "ocr_text, content='pdf_pages', content_rowid='id', tokenize='trigram')"
        )
        conn.execute(
            "CREATE TRIGGER pdf_pages_fts_au AFTER UPDATE ON pdf_pages BEGIN "
            "INSERT INTO pdf_pages_fts(pdf_pages_fts, rowid, ocr_text) "
            "VALUES ('delete', old.id, old.ocr_text); "
            "INSERT INTO pdf_pages_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text); END"
        )
        conn.execute("INSERT INTO pdf_pages_fts(pdf_pages_fts) VALUES ('rebuild')")
        conn.execute("UPDATE schema_version SET version = 27")
        conn.commit()
        conn.close()

        conn = Db.connect(db_path)
        try:
            names = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name LIKE 'pdf_pages_%'"
                )
            }
            assert not {n for n in names if n.startswith("pdf_pages_fts")}
            assert {"pdf_pages_trigram", "pdf_pages_words"} <= names
            assert conn.execute(
                "SELECT rowid FROM pdf_pages_trigram WHERE ocr_text LIKE '%arge inv%'"
            ).fetchone()
            assert conn.execute(
                "SELECT rowid FROM pdf_pages_words WHERE pdf_pages_words MATCH '\"invoices\"'"
            ).fetchone()
            conn.execute(
                "INSERT INTO pdf_pages_trigram(pdf_pages_trigram) VALUES ('integrity-check')"
            )
            conn.execute("INSERT INTO pdf_pages_words(pdf_pages_words) VALUES ('integrity-check')")
        finally:
            conn.close()

    def test_pdf_pages_trigram_stays_in_sync_via_triggers(self, tmp_path):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            conn.execute(
                "INSERT INTO sources (path, source_type, status, added_at) "
                "VALUES ('/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00')"
            )
            conn.execute("INSERT INTO documents (created_at) VALUES ('2026-01-01T00:00:00+00:00')")
            conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
                "VALUES (1, 1, '/docs/a.pdf', 'pdf', 'indexed')"
            )
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (1, 1, 'original wording', 0.9)"
            )
            conn.commit()

            assert (
                conn.execute(
                    "SELECT rowid FROM pdf_pages_trigram WHERE ocr_text LIKE '%original%'"
                ).fetchone()
                is not None
            )

            conn.execute("UPDATE pdf_pages SET ocr_text = 'revised wording' WHERE document_id = 1")
            conn.commit()
            assert (
                conn.execute(
                    "SELECT rowid FROM pdf_pages_trigram WHERE ocr_text LIKE '%original%'"
                ).fetchone()
                is None
            )
            assert (
                conn.execute(
                    "SELECT rowid FROM pdf_pages_trigram WHERE ocr_text LIKE '%revised%'"
                ).fetchone()
                is not None
            )

            conn.execute("DELETE FROM pdf_pages WHERE document_id = 1")
            conn.commit()
            assert conn.execute("SELECT rowid FROM pdf_pages_trigram").fetchone() is None

            # An external-content FTS5 index that's fallen out of sync with its
            # content table fails this integrity check - a passing 'integrity-check'
            # command confirms the triggers left it consistent throughout.
            conn.execute(
                "INSERT INTO pdf_pages_trigram(pdf_pages_trigram) VALUES ('integrity-check')"
            )
        finally:
            conn.close()

    def test_connect_migrates_document_index_allows_unsupported(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # A schema 25 database: file_type/status CHECKs don't allow 'unsupported' yet.
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (25);
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL,
                last_scanned_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE document_index (
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
            INSERT INTO sources (id, path, source_type, status, added_at)
                VALUES (1, '/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00');
            INSERT INTO documents (id, created_at) VALUES (1, '2026-01-01T00:00:00+00:00');
            INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
                VALUES (1, 1, 1, '/docs/a.pdf', 'pdf', 'indexed');
            """
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            assert (
                conn.execute("SELECT status FROM document_index WHERE id = 1").fetchone()["status"]
                == "indexed"
            )
            conn.execute(
                "INSERT INTO document_index "
                "(source_id, document_id, file_path, file_type, status, error_message) "
                "VALUES (1, 1, '/docs/notes.txt', 'unsupported', 'unsupported', "
                "'Unsupported file format: .txt')"
            )
            conn.commit()
        finally:
            conn.close()

    def test_connect_adds_and_backfills_char_count(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        # Simulate a v26 database: pages tables without `char_count`.
        Db.connect(db_path).close()
        old_conn = sqlite3.connect(db_path)
        old_conn.executescript(
            """
            INSERT INTO sources (id, path, source_type, status, added_at)
                VALUES (1, '/docs', 'folder', 'indexed', '2024-01-01');
            INSERT INTO documents (created_at) VALUES ('2024-01-01'), ('2024-01-01');
            INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
                VALUES (1, 1, 1, '/a.pdf', 'pdf', 'indexed'),
                       (2, 1, 2, '/b.png', 'image', 'indexed');
            INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence)
                VALUES (1, 1, 'hello', 0.9);
            INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (2, 'hi there', 0.9);
            ALTER TABLE pdf_pages DROP COLUMN char_count;
            ALTER TABLE image_pages DROP COLUMN char_count;
            UPDATE schema_version SET version = 26;
            """
        )
        old_conn.commit()
        old_conn.close()

        conn = Db.connect(db_path)
        try:
            assert conn.execute("SELECT char_count FROM pdf_pages").fetchone()["char_count"] == 5
            assert conn.execute("SELECT char_count FROM image_pages").fetchone()["char_count"] == 8
            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_adds_reindex_pending_to_a_v28_database(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        conn = Db.connect(db_path)
        conn.execute(
            "INSERT INTO sources (path, source_type, added_at) VALUES ('/d', 'folder', 'x')"
        )
        conn.execute("INSERT INTO documents (created_at) VALUES ('x')")
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (1, 1, '/d/a.png', 'image', 'indexed')"
        )
        conn.execute("ALTER TABLE document_index DROP COLUMN reindex_pending")
        conn.execute("UPDATE schema_version SET version = 28")
        conn.commit()
        conn.close()

        conn = Db.connect(db_path)
        try:
            row = conn.execute("SELECT status, reindex_pending FROM document_index").fetchone()
            assert (row["status"], row["reindex_pending"]) == ("indexed", 0)
            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()
