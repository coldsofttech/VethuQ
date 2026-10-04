import sqlite3

import pytest
from vethuq_core.db import Db

OLD_PROCESSING = """
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
)
"""
OLD_CONFIDENCE = """
CREATE TABLE confidence_metrics (
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'image')),
    process_type TEXT NOT NULL CHECK (process_type IN ('native', 'ocr', 'mixed')),
    page_count INTEGER NOT NULL DEFAULT 0,
    avg_confidence REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (file_type, process_type)
)
"""


def _doc(conn, row_id, path, file_type, *, seconds=None, size=1000, mem=100.0, cpu=10.0):
    conn.execute("INSERT INTO documents (id, created_at) VALUES (?, 'x')", (row_id,))
    completed = f"2026-01-01T00:00:{int(seconds):02d}+00:00" if seconds is not None else None
    started = "2026-01-01T00:00:00+00:00" if seconds is not None else None
    conn.execute(
        "INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status, "
        "file_size_bytes, started_at, completed_at, peak_memory_mb, cpu_percent) "
        "VALUES (?, 1, ?, ?, ?, 'indexed', ?, ?, ?, ?, ?)",
        (row_id, row_id, path, file_type, size, started, completed, mem, cpu),
    )


@pytest.fixture
def v29_db(tmp_path):
    """A v29 database: image statistics blended across PNG and JPG, indexed files on disk."""
    db_path = tmp_path / "vethuq.db"
    conn = Db.connect(db_path)
    conn.execute("DROP TABLE processing_metrics")
    conn.execute("DROP TABLE confidence_metrics")
    conn.execute(OLD_PROCESSING)
    conn.execute(OLD_CONFIDENCE)
    conn.execute(
        "INSERT INTO processing_metrics VALUES (1, 'image', 'small', 3, 99.0, 1, 1, 'old')"
    )
    conn.execute("INSERT INTO confidence_metrics VALUES ('image', 'ocr', 3, 0.5, 'old')")
    conn.execute(
        "INSERT INTO sources (id, path, source_type, added_at) VALUES (1, '/x', 'folder', 'x')"
    )
    _doc(conn, 1, "/x/a.png", "image", seconds=2, size=1000, mem=100.0, cpu=10.0)
    _doc(conn, 2, "/x/b.png", "image", seconds=4, size=2000, mem=200.0, cpu=30.0)
    _doc(conn, 3, "/x/c.JPEG", "image", seconds=10, size=4_000_000, mem=50.0, cpu=5.0)
    _doc(conn, 4, "/x/d.pdf", "pdf", seconds=6, size=600_000)
    # A duplicate of a.png: no pages of its own, never OCR'd, so it is not counted.
    conn.execute("INSERT INTO documents (id, created_at) VALUES (5, 'x')")
    conn.execute(
        "INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status, "
        "file_size_bytes, started_at, completed_at) VALUES "
        "(5, 1, 1, '/x/dup.png', 'image', 'indexed', 1000, "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00')"
    )
    for row_id, confidence in ((1, 0.6), (2, 1.0), (3, 0.2)):
        conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (?, 't', ?)",
            (row_id, confidence),
        )
    conn.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence, source) VALUES "
        "(4, 1, 't', 1.0, 'native'), (4, 2, 't', 0.5, 'ocr'), (4, 3, 't', 0.7, 'ocr')"
    )
    conn.execute(
        "INSERT INTO document_phases (document_id, phase, started_at, completed_at, "
        "duration_seconds, peak_memory_mb, cpu_percent) "
        "VALUES (2, 2, 'x', 'y', 40.0, 300.0, 20.0)"
    )
    conn.execute("UPDATE schema_version SET version = 29")
    conn.commit()
    conn.close()
    return db_path


def _processing(conn):
    return {
        (r["phase"], r["file_type"], r["extension"], r["size_bucket"]): r
        for r in conn.execute("SELECT * FROM processing_metrics")
    }


class TestStatsPerExtensionMigration:
    def test_processing_metrics_are_rebuilt_per_extension(self, v29_db):
        conn = Db.connect(v29_db)
        try:
            rows = _processing(conn)

            assert set(rows) == {
                (1, "image", "png", "small"),
                (1, "image", "jpg", "large"),
                (1, "pdf", "pdf", "medium"),
                (2, "image", "png", "small"),
            }
            png = rows[(1, "image", "png", "small")]
            assert png["document_count"] == 2
            assert png["avg_duration_seconds"] == pytest.approx(3.0)
            assert png["avg_peak_memory_mb"] == pytest.approx(150.0)
            assert png["avg_cpu_percent"] == pytest.approx(20.0)
            jpg = rows[(1, "image", "jpg", "large")]
            assert (jpg["document_count"], jpg["avg_duration_seconds"]) == (1, 10.0)
            deeper = rows[(2, "image", "png", "small")]
            assert (deeper["document_count"], deeper["avg_duration_seconds"]) == (1, 40.0)
            assert deeper["avg_peak_memory_mb"] == pytest.approx(300.0)
            # the old blended 'image' row is gone
            assert not any(r["avg_duration_seconds"] == 99.0 for r in rows.values())
        finally:
            conn.close()

    def test_confidence_metrics_are_rebuilt_per_extension(self, v29_db):
        conn = Db.connect(v29_db)
        try:
            rows = {
                (r["file_type"], r["extension"], r["process_type"]): (
                    r["page_count"],
                    r["avg_confidence"],
                )
                for r in conn.execute("SELECT * FROM confidence_metrics")
            }

            assert rows[("image", "png", "ocr")] == (2, pytest.approx(0.8))
            assert rows[("image", "jpg", "ocr")] == (1, pytest.approx(0.2))
            assert rows[("pdf", "pdf", "native")] == (1, pytest.approx(1.0))
            assert rows[("pdf", "pdf", "ocr")] == (2, pytest.approx(0.6))
            assert len(rows) == 4
        finally:
            conn.close()

    def test_database_keeps_working_after_the_migration(self, v29_db):
        conn = Db.connect(v29_db)
        try:
            version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
            assert version == Db.SCHEMA_VERSION
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(processing_metrics)")}
            assert "extension" in columns
            conn.execute(
                "INSERT INTO processing_metrics (phase, file_type, extension, size_bucket, "
                "updated_at) VALUES (1, 'image', 'gif', 'small', 'now')"
            )
        finally:
            conn.close()

    def test_empty_database_migrates_to_empty_statistics(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        conn = Db.connect(db_path)
        conn.execute("DROP TABLE processing_metrics")
        conn.execute("DROP TABLE confidence_metrics")
        conn.execute(OLD_PROCESSING)
        conn.execute(OLD_CONFIDENCE)
        conn.execute("UPDATE schema_version SET version = 29")
        conn.commit()
        conn.close()

        conn = Db.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM processing_metrics").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM confidence_metrics").fetchone()[0] == 0
        finally:
            conn.close()


def test_sqlite_is_new_enough_for_drop_column():
    # The v29 migration test relies on DROP COLUMN (SQLite 3.35+).
    assert sqlite3.sqlite_version_info >= (3, 35)
