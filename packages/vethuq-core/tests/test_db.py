import sqlite3

from vethuq_core.db import SCHEMA_VERSION, connect


def test_connect_migrates_index_runs_missing_mode_column(tmp_path):
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

    conn = connect(db_path)
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
        assert version == SCHEMA_VERSION
    finally:
        conn.close()
