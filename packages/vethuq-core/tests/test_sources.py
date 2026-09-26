import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from vethuq_core.db import connect
from vethuq_core.sources import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    SourcePathError,
    add_source,
    list_sources,
    purge_expired_removed_sources,
    remove_source,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = connect(db_path)
    yield connection
    connection.close()


def test_add_source_folder(conn: sqlite3.Connection, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()

    source = add_source(conn, folder)

    assert source.source_type == "folder"
    assert source.path == str(folder.resolve())
    assert source.status == "pending"
    assert source.is_active is True


def test_add_source_file(conn: sqlite3.Connection, tmp_path):
    file_path = tmp_path / "report.pdf"
    file_path.write_text("fake pdf content")

    source = add_source(conn, file_path)

    assert source.source_type == "file"
    assert source.path == str(file_path.resolve())


def test_add_source_missing_path_raises(conn: sqlite3.Connection, tmp_path):
    missing = tmp_path / "does-not-exist"

    with pytest.raises(SourcePathError):
        add_source(conn, missing)


def test_add_source_duplicate_raises(conn: sqlite3.Connection, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    add_source(conn, folder)

    with pytest.raises(SourceAlreadyExistsError):
        add_source(conn, folder)


def test_add_source_dedupes_relative_and_absolute(conn: sqlite3.Connection, tmp_path, monkeypatch):
    folder = tmp_path / "docs"
    folder.mkdir()
    monkeypatch.chdir(tmp_path)

    add_source(conn, folder)

    with pytest.raises(SourceAlreadyExistsError):
        add_source(conn, "docs")


def test_list_sources_excludes_inactive_by_default(conn: sqlite3.Connection, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    added = add_source(conn, folder)
    remove_source(conn, added.id)

    assert list_sources(conn) == []
    assert len(list_sources(conn, include_inactive=True)) == 1


def test_remove_source_by_path(conn: sqlite3.Connection, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    add_source(conn, folder)

    removed = remove_source(conn, folder)

    assert removed.is_active is False
    assert removed.status == "removed"
    assert removed.removed_at is not None


def test_remove_source_not_found_raises(conn: sqlite3.Connection):
    with pytest.raises(SourceNotFoundError):
        remove_source(conn, 999)


def test_add_source_reactivates_removed_source(conn: sqlite3.Connection, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    original = add_source(conn, folder)
    remove_source(conn, original.id)

    readded = add_source(conn, folder)

    assert readded.id == original.id
    assert readded.is_active is True
    assert readded.status == "pending"
    assert readded.last_scanned_at is None
    assert readded.removed_at is None
    assert len(list_sources(conn)) == 1


def test_purge_expired_removed_sources_deletes_stale_removed_rows(
    conn: sqlite3.Connection, tmp_path
):
    folder = tmp_path / "docs"
    folder.mkdir()
    source = add_source(conn, folder)
    document_id = conn.execute(
        "INSERT INTO document_index (source_id, file_path, file_type, status) "
        "VALUES (?, '/docs/a.pdf', 'pdf', 'indexed')",
        (source.id,),
    ).lastrowid
    conn.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
        "VALUES (?, 1, 'text', 0.9)",
        (document_id,),
    )
    conn.commit()
    remove_source(conn, source.id)
    stale_removed_at = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    conn.execute("UPDATE sources SET removed_at = ? WHERE id = ?", (stale_removed_at, source.id))
    conn.commit()

    purged = purge_expired_removed_sources(conn, retention_minutes=30)

    assert purged == 1
    assert conn.execute("SELECT * FROM sources WHERE id = ?", (source.id,)).fetchone() is None
    assert (
        conn.execute("SELECT * FROM document_index WHERE source_id = ?", (source.id,)).fetchone()
        is None
    )
    assert (
        conn.execute("SELECT * FROM pdf_pages WHERE document_id = ?", (document_id,)).fetchone()
        is None
    )


def test_purge_expired_removed_sources_keeps_recently_removed(conn: sqlite3.Connection, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    source = add_source(conn, folder)
    remove_source(conn, source.id)

    purged = purge_expired_removed_sources(conn, retention_minutes=30)

    assert purged == 0
    assert conn.execute("SELECT * FROM sources WHERE id = ?", (source.id,)).fetchone() is not None
