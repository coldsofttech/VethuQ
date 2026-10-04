import sqlite3

from vethuq_core.db import Db
from vethuq_core.db.backup import Backup
from vethuq_core.db.integrity import IntegrityCheck
from vethuq_core.sources import Sources
from vethuq_core.storage.sqlite import SqliteStorage


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
                if row["key"] not in (IntegrityCheck.LAST_RUN_AT_KEY, Backup.LAST_RUN_AT_KEY)
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
        from vethuq_core.readers import PageResult

        assert PageResult("text", 1.0, "native").phase_columns() == (1, "")
        assert PageResult("text", 0.9, "ocr").phase_columns() == (1, "0")

        db_path = tmp_path / "v18.db"
        setup = Db.connect(db_path)
        folder = tmp_path / "src"
        folder.mkdir()
        source = Sources.add(SqliteStorage(setup), folder)
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

    def test_migration_v20_adds_phase_to_processing_metrics(self, tmp_path):
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
            # Since v30 the averages are rebuilt per extension from the stored documents (see
            # `test_stats_per_extension_migration.py`), so a table with none starts empty.
            columns = {
                row["name"] for row in migrated.execute("PRAGMA table_info(processing_metrics)")
            }
            assert {"phase", "extension"} <= columns
            assert migrated.execute("SELECT * FROM processing_metrics").fetchone() is None
        finally:
            migrated.close()
