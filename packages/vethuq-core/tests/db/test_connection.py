import sqlite3
from pathlib import Path

from vethuq_core.db import Db


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
            assert not Path(f"{db_path}.bkp").exists()
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
            backup_path = Path(f"{db_path}.bkp")
            assert backup_path.exists()

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
