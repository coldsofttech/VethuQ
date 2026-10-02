import sqlite3

from vethuq_core.db import Db
from vethuq_core.source import Sources


class TestPhaseMigration:
    def test_migration_adds_phase_columns_to_existing_pages(self, tmp_path):
        db_path = tmp_path / "old.db"
        old = sqlite3.connect(db_path)
        old.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (16);
            CREATE TABLE image_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL,
                ocr_text TEXT NOT NULL, confidence REAL NOT NULL, ocr_engine TEXT,
                language TEXT, image_width INTEGER, image_height INTEGER
            );
            INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (1, 'hi', 0.9);
            """
        )
        old.commit()
        old.close()

        migrated = Db.connect(db_path)
        try:
            row = migrated.execute("SELECT ocr_phase, ocr_angles FROM image_pages").fetchone()
            assert (row["ocr_phase"], row["ocr_angles"]) == (1, "0")
        finally:
            migrated.close()

    def test_migration_renames_old_setting_keys_keeping_values(self, tmp_path):
        db_path = tmp_path / "old.db"
        old = sqlite3.connect(db_path)
        old.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (17);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO settings (key, value) VALUES
                ('thread_workers', '4'),
                ('stale_lock', 'disable'),
                ('ocr_engine', 'deep'),
                ('index_ocr_retry_attempts', '9'),
                ('ocr_retry_attempts', '1'),
                ('gpu_enabled', 'true');
            """
        )
        old.commit()
        old.close()

        migrated = Db.connect(db_path)
        try:
            settings = {
                row["key"]: row["value"]
                for row in migrated.execute("SELECT key, value FROM settings")
            }
        finally:
            migrated.close()

        assert settings == {
            "index_thread_workers": "4",
            "index_stale_lock": "disable",
            "index_engine": "deep",
            "index_ocr_retry_attempts": "9",  # the already-present new key wins
            "gpu_enabled": "true",
        }

    def test_native_pages_are_stored_at_the_quick_phase_and_migrated_there(self, tmp_path):
        from vethuq_core.ocr import PageResult

        assert PageResult("text", 1.0, "native").phase_columns() == (1, "")
        assert PageResult("text", 0.9, "ocr").phase_columns() == (1, "0")

        db_path = tmp_path / "v18.db"
        setup = Db.connect(db_path)
        folder = tmp_path / "src"
        folder.mkdir()
        source = Sources.add(setup, folder)
        setup.execute("INSERT INTO documents (id, created_at) VALUES (1, '2026-01-01')")
        setup.execute(
            "INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status) "
            "VALUES (1, ?, 1, 'x.pdf', 'pdf', 'indexed')",
            (source.id,),
        )
        setup.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source, "
            "ocr_phase, ocr_angles) VALUES (1, 1, 'x', 1.0, 'native', 3, '')"
        )
        setup.execute("UPDATE schema_version SET version = 18")
        setup.commit()
        setup.close()

        migrated = Db.connect(db_path)
        try:
            assert migrated.execute("SELECT ocr_phase FROM pdf_pages").fetchone()["ocr_phase"] == 1
        finally:
            migrated.close()

    def test_migration_v20_makes_existing_processing_metrics_phase_1(self, tmp_path):
        db_path = tmp_path / "v19.db"
        setup = Db.connect(db_path)
        setup.execute("DROP TABLE processing_metrics")
        setup.execute(
            "CREATE TABLE processing_metrics (file_type TEXT NOT NULL, size_bucket TEXT NOT NULL, "
            "document_count INTEGER NOT NULL DEFAULT 0, "
            "avg_duration_seconds REAL NOT NULL DEFAULT 0, "
            "avg_peak_memory_mb REAL NOT NULL DEFAULT 0, avg_cpu_percent REAL NOT NULL DEFAULT 0, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (file_type, size_bucket))"
        )
        setup.execute(
            "INSERT INTO processing_metrics VALUES ('pdf', 'small', 4, 2.5, 100, 10, 'now')"
        )
        setup.execute("UPDATE schema_version SET version = 19")
        setup.commit()
        setup.close()

        migrated = Db.connect(db_path)
        try:
            row = migrated.execute("SELECT * FROM processing_metrics").fetchone()
            assert (row["phase"], row["document_count"], row["avg_duration_seconds"]) == (1, 4, 2.5)
        finally:
            migrated.close()


class TestEmlMigration:
    def test_v25_database_gains_eml_file_type_keeping_rows(self, tmp_path):
        db_path = tmp_path / "v25.db"
        old = sqlite3.connect(db_path)
        # Rebuild a v25 database: the pre-'eml' CHECKs, a row in each affected table.
        old.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (25);
            CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                added_at TEXT NOT NULL, last_scanned_at TEXT, is_active INTEGER NOT NULL DEFAULT 1,
                removed_at TEXT);
            CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                file_path TEXT);
            CREATE TABLE document_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id),
                document_id INTEGER NOT NULL REFERENCES documents(id),
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'indexed', 'error', 'removed')),
                error_message TEXT, indexed_at TEXT, started_at TEXT, completed_at TEXT,
                file_size_bytes INTEGER, sha256 TEXT, mtime REAL, created_at TEXT,
                modified_at TEXT, removed_at TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
                peak_memory_mb REAL, cpu_percent REAL
            );
            CREATE TABLE processing_metrics (
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
            CREATE TABLE confidence_metrics (
                file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
                process_type TEXT NOT NULL CHECK (process_type IN ('native', 'ocr', 'mixed')),
                page_count INTEGER NOT NULL DEFAULT 0,
                avg_confidence REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (file_type, process_type)
            );
            INSERT INTO sources (path, source_type, added_at) VALUES ('/s', 'folder', 'now');
            INSERT INTO documents (created_at) VALUES ('now');
            INSERT INTO document_index (source_id, document_id, file_path, file_type)
                VALUES (1, 1, '/s/a.pdf', 'pdf');
            INSERT INTO processing_metrics (file_type, size_bucket, document_count, updated_at)
                VALUES ('image', 'small', 3, 'now');
            INSERT INTO confidence_metrics (file_type, process_type, page_count, updated_at)
                VALUES ('pdf', 'native', 2, 'now');
            """
        )
        old.commit()
        old.close()

        migrated = Db.connect(db_path)
        try:
            assert (
                migrated.execute("SELECT file_path FROM document_index").fetchone()[0] == "/s/a.pdf"
            )
            assert (
                migrated.execute("SELECT document_count FROM processing_metrics").fetchone()[0] == 3
            )
            assert migrated.execute("SELECT page_count FROM confidence_metrics").fetchone()[0] == 2
            migrated.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type) "
                "VALUES (1, 1, '/s/m.eml', 'eml')"
            )
            migrated.execute(
                "INSERT INTO processing_metrics (file_type, size_bucket, updated_at) "
                "VALUES ('eml', 'small', 'now')"
            )
            migrated.execute(
                "INSERT INTO confidence_metrics (file_type, process_type, updated_at) "
                "VALUES ('eml', 'native', 'now')"
            )
        finally:
            migrated.close()
