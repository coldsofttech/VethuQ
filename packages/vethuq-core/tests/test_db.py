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


def test_connect_migrates_document_index_missing_file_size_column(tmp_path):
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

    conn = connect(db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        assert "file_size_bytes" in columns

        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == SCHEMA_VERSION
    finally:
        conn.close()


def test_connect_migrates_document_index_missing_checksum_columns(tmp_path):
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

    conn = connect(db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        assert "checksum" in columns
        assert "duplicate_of_id" in columns

        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == SCHEMA_VERSION
    finally:
        conn.close()


def test_connect_creates_processing_metrics_table(tmp_path):
    conn = connect(tmp_path / "vethuq.db")
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
        assert columns == {
            "file_type",
            "document_count",
            "avg_duration_seconds",
            "avg_confidence",
            "pages_native",
            "pages_ocr",
            "pages_mixed",
            "updated_at",
        }
    finally:
        conn.close()
