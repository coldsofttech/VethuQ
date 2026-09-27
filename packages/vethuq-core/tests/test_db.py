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


def test_connect_migrates_document_index_missing_mtime_column(tmp_path):
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

    conn = connect(db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_index)")}
        assert "mtime" in columns

        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == SCHEMA_VERSION
    finally:
        conn.close()


def test_connect_migrates_document_index_status_check_and_removed_at(tmp_path):
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

    conn = connect(db_path)
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
        assert version == SCHEMA_VERSION
    finally:
        conn.close()


def test_connect_creates_processing_metrics_table(tmp_path):
    conn = connect(tmp_path / "vethuq.db")
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
        assert columns == {
            "file_type",
            "size_bucket",
            "document_count",
            "avg_duration_seconds",
            "avg_peak_memory_mb",
            "avg_cpu_percent",
            "updated_at",
        }
    finally:
        conn.close()


def test_connect_creates_confidence_metrics_table(tmp_path):
    conn = connect(tmp_path / "vethuq.db")
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(confidence_metrics)")}
        assert columns == {
            "file_type",
            "process_type",
            "page_count",
            "avg_confidence",
            "updated_at",
        }
    finally:
        conn.close()


def test_connect_migrates_processing_metrics_confidence_split(tmp_path):
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
            checksum TEXT,
            removed_at TEXT
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
             pages_native, pages_ocr, pages_mixed, avg_peak_memory_mb, avg_cpu_percent, updated_at)
        VALUES
            ('pdf', 1, 5.0, 0.8, 1, 1, 1, 100.0, 10.0, '2026-01-01T00:00:00+00:00'),
            ('image', 1, 2.0, 0.7, 0, 1, 0, 50.0, 5.0, '2026-01-01T00:00:00+00:00');
        """
    )
    old_conn.commit()
    old_conn.close()

    conn = connect(db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
        assert "avg_confidence" not in columns
        assert "pages_native" not in columns

        pdf_metrics = conn.execute(
            "SELECT document_count, avg_duration_seconds, avg_peak_memory_mb, avg_cpu_percent "
            "FROM processing_metrics WHERE file_type = 'pdf' AND size_bucket = 'medium'"
        ).fetchone()
        assert pdf_metrics["document_count"] == 1
        assert pdf_metrics["avg_duration_seconds"] == 5.0

        confidence_rows = {
            (row["file_type"], row["process_type"]): (row["page_count"], row["avg_confidence"])
            for row in conn.execute(
                "SELECT file_type, process_type, page_count, avg_confidence FROM confidence_metrics"
            )
        }
        assert confidence_rows[("pdf", "native")] == (1, 1.0)
        assert confidence_rows[("pdf", "ocr")] == (1, 0.6)
        assert confidence_rows[("pdf", "mixed")] == (1, 0.8)
        assert confidence_rows[("image", "ocr")] == (1, 0.7)

        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        assert version == SCHEMA_VERSION
    finally:
        conn.close()
