import gzip
import sqlite3

import pytest
from vethuq_core.db import Db, SchemaVersionError
from vethuq_core.db.backup import Backup


class TestConnection:
    def test_connect_enables_wal_mode_and_busy_timeout(self, tmp_path):
        conn = Db.connect(tmp_path / "vethuq.db")
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == Db.BUSY_TIMEOUT_MS
        finally:
            conn.close()

    def test_connect_does_not_create_backup_for_a_fresh_database(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        conn = Db.connect(db_path)
        try:
            assert not [b for b in Backup.entries(db_path) if "premigration" in b.name]
        finally:
            conn.close()

    def test_connect_backs_up_database_before_migrating(self, tmp_path):
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
            backups = [b for b in Backup.entries(db_path) if "premigration" in b.name]
            assert len(backups) == 1
            backup_path = tmp_path / "pre-migration.db"
            backup_path.write_bytes(gzip.decompress(backups[0].path.read_bytes()))

            # The backup is a snapshot of the database as it was *before*
            # migrating - not a copy of the now-migrated `db_path`.
            backup_conn = sqlite3.connect(backup_path)
            try:
                version = backup_conn.execute("SELECT version FROM schema_version").fetchone()[0]
                assert version == 5

                columns = {row[1] for row in backup_conn.execute("PRAGMA table_info(index_runs)")}
                assert "mode" not in columns
            finally:
                backup_conn.close()

            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
        finally:
            conn.close()

    def test_connect_rejects_database_with_newer_schema_version(self, tmp_path):
        db_path = tmp_path / "vethuq.db"

        newer = sqlite3.connect(db_path)
        newer.executescript(
            f"""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES ({Db.SCHEMA_VERSION + 1});
            """
        )
        newer.commit()
        newer.close()

        with pytest.raises(SchemaVersionError, match="newer"):
            Db.connect(db_path)

        # Untouched: no tables added, version not downgraded.
        check = sqlite3.connect(db_path)
        try:
            tables = {
                r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert tables == {"schema_version"}
            assert check.execute("SELECT version FROM schema_version").fetchone()[0] == (
                Db.SCHEMA_VERSION + 1
            )
        finally:
            check.close()
