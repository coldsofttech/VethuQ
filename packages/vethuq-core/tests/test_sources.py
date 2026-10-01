import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from vethuq_core.db import Db
from vethuq_core.sources import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    SourcePathError,
    _refresh_document_paths,
    add_source,
    list_sources,
    purge_expired_removed_sources,
    remove_source,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = Db.connect(db_path)
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


def _insert_document(conn: sqlite3.Connection, document_id: int | None = None, **fields) -> int:
    """Insert a `document_index` row for a test, creating a fresh `documents` row if needed."""
    if document_id is None:
        document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
        ).lastrowid
    columns = ["document_id", *fields.keys()]
    placeholders = ", ".join("?" * len(columns))
    row_id = conn.execute(
        f"INSERT INTO document_index ({', '.join(columns)}) VALUES ({placeholders})",
        (document_id, *fields.values()),
    ).lastrowid
    assert row_id is not None
    return row_id


def test_purge_expired_removed_sources_deletes_stale_removed_rows(
    conn: sqlite3.Connection, tmp_path
):
    folder = tmp_path / "docs"
    folder.mkdir()
    source = add_source(conn, folder)
    document_id = _insert_document(
        conn, source_id=source.id, file_path="/docs/a.pdf", file_type="pdf", status="indexed"
    )
    logical_document_id = conn.execute(
        "SELECT document_id FROM document_index WHERE id = ?", (document_id,)
    ).fetchone()["document_id"]
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
    # The logical document is now unreferenced by any physical row - pruned too.
    assert (
        conn.execute("SELECT * FROM documents WHERE id = ?", (logical_document_id,)).fetchone()
        is None
    )


def test_purge_expired_removed_sources_promotes_surviving_duplicate(
    conn: sqlite3.Connection, tmp_path
):
    removed_folder = tmp_path / "removed"
    removed_folder.mkdir()
    removed_source = add_source(conn, removed_folder)
    (tmp_path / "kept.pdf").write_bytes(b"pdf bytes")
    kept_source = add_source(conn, tmp_path / "kept.pdf")

    original_id = _insert_document(
        conn,
        source_id=removed_source.id,
        file_path="/removed/original.pdf",
        file_type="pdf",
        status="indexed",
        sha256="abc",
    )
    logical_document_id = conn.execute(
        "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
    ).fetchone()["document_id"]
    conn.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
        "VALUES (?, 1, 'shared text', 0.9)",
        (original_id,),
    )
    duplicate_id = _insert_document(
        conn,
        document_id=logical_document_id,
        source_id=kept_source.id,
        file_path="/kept/copy.pdf",
        file_type="pdf",
        status="indexed",
        sha256="abc",
    )
    conn.commit()

    remove_source(conn, removed_source.id)
    stale_removed_at = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    conn.execute(
        "UPDATE sources SET removed_at = ? WHERE id = ?", (stale_removed_at, removed_source.id)
    )
    conn.commit()

    purged = purge_expired_removed_sources(conn, retention_minutes=30)

    assert purged == 1
    promoted = conn.execute("SELECT * FROM document_index WHERE id = ?", (duplicate_id,)).fetchone()
    assert promoted["document_id"] == logical_document_id
    page = conn.execute("SELECT * FROM pdf_pages WHERE document_id = ?", (duplicate_id,)).fetchone()
    assert page["ocr_text"] == "shared text"
    assert (
        conn.execute("SELECT * FROM pdf_pages WHERE document_id = ?", (original_id,)).fetchone()
        is None
    )
    # The logical document survives, still referenced by the promoted duplicate.
    assert (
        conn.execute("SELECT * FROM documents WHERE id = ?", (logical_document_id,)).fetchone()
        is not None
    )


def test_purge_expired_removed_sources_across_two_expired_sources_with_duplicate(
    conn: sqlite3.Connection, tmp_path
):
    """Regression: both the original and its duplicate are doomed, in different sources.

    `_promote_surviving_duplicate` finds no surviving peer to hand pages off to
    since both are doomed - the whole content cluster (and its shared
    `documents` row) is being deleted together.
    """
    original_folder = tmp_path / "original_source"
    original_folder.mkdir()
    original_source = add_source(conn, original_folder)
    duplicate_folder = tmp_path / "duplicate_source"
    duplicate_folder.mkdir()
    duplicate_source = add_source(conn, duplicate_folder)

    original_id = _insert_document(
        conn,
        source_id=original_source.id,
        file_path="/original_source/a.pdf",
        file_type="pdf",
        status="indexed",
        sha256="abc",
    )
    logical_document_id = conn.execute(
        "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
    ).fetchone()["document_id"]
    duplicate_id = _insert_document(
        conn,
        document_id=logical_document_id,
        source_id=duplicate_source.id,
        file_path="/duplicate_source/a.pdf",
        file_type="pdf",
        status="indexed",
        sha256="abc",
    )
    conn.commit()

    remove_source(conn, original_source.id)
    remove_source(conn, duplicate_source.id)
    stale_removed_at = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    conn.execute(
        "UPDATE sources SET removed_at = ? WHERE id IN (?, ?)",
        (stale_removed_at, original_source.id, duplicate_source.id),
    )
    conn.commit()

    purged = purge_expired_removed_sources(conn, retention_minutes=30)

    assert purged == 2
    assert (
        conn.execute("SELECT * FROM document_index WHERE id = ?", (original_id,)).fetchone() is None
    )
    assert (
        conn.execute("SELECT * FROM document_index WHERE id = ?", (duplicate_id,)).fetchone()
        is None
    )
    assert (
        conn.execute("SELECT * FROM documents WHERE id = ?", (logical_document_id,)).fetchone()
        is None
    )


def test_purge_expired_removed_sources_clears_stale_index_runs_target(
    conn: sqlite3.Connection, tmp_path
):
    folder = tmp_path / "docs"
    folder.mkdir()
    source = add_source(conn, folder)
    run_by_id = conn.execute(
        "INSERT INTO index_runs (target, started_at) VALUES (?, ?)",
        (str(source.id), datetime.now(UTC).isoformat()),
    ).lastrowid
    run_by_path = conn.execute(
        "INSERT INTO index_runs (target, started_at) VALUES (?, ?)",
        (source.path, datetime.now(UTC).isoformat()),
    ).lastrowid
    conn.commit()

    remove_source(conn, source.id)
    stale_removed_at = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    conn.execute("UPDATE sources SET removed_at = ? WHERE id = ?", (stale_removed_at, source.id))
    conn.commit()

    purge_expired_removed_sources(conn, retention_minutes=30)

    for run_id in (run_by_id, run_by_path):
        row = conn.execute("SELECT target FROM index_runs WHERE id = ?", (run_id,)).fetchone()
        assert row["target"] is None


def test_purge_expired_removed_sources_keeps_recently_removed(conn: sqlite3.Connection, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    source = add_source(conn, folder)
    remove_source(conn, source.id)

    purged = purge_expired_removed_sources(conn, retention_minutes=30)

    assert purged == 0
    assert conn.execute("SELECT * FROM sources WHERE id = ?", (source.id,)).fetchone() is not None


def test_document_primary_path_moves_to_surviving_copy_on_purge(conn: sqlite3.Connection, tmp_path):
    removed_folder = tmp_path / "removed"
    removed_folder.mkdir()
    removed_source = add_source(conn, removed_folder)
    (tmp_path / "kept.pdf").write_bytes(b"pdf bytes")
    kept_source = add_source(conn, tmp_path / "kept.pdf")

    original_id = _insert_document(
        conn,
        source_id=removed_source.id,
        file_path="/removed/original.pdf",
        file_type="pdf",
        status="indexed",
        sha256="abc",
    )
    logical_document_id = conn.execute(
        "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
    ).fetchone()["document_id"]
    _insert_document(
        conn,
        document_id=logical_document_id,
        source_id=kept_source.id,
        file_path="/kept/copy.pdf",
        file_type="pdf",
        status="indexed",
        sha256="abc",
    )
    _refresh_document_paths(conn, {logical_document_id})
    assert _primary_path(conn, logical_document_id) == "/removed/original.pdf"

    remove_source(conn, removed_source.id)
    stale_removed_at = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    conn.execute(
        "UPDATE sources SET removed_at = ? WHERE id = ?", (stale_removed_at, removed_source.id)
    )
    conn.commit()

    purge_expired_removed_sources(conn, retention_minutes=30)

    assert _primary_path(conn, logical_document_id) == "/kept/copy.pdf"


def test_document_primary_path_skips_removed_copies_and_is_null_when_none_left(
    conn: sqlite3.Connection, tmp_path
):
    folder = tmp_path / "docs"
    folder.mkdir()
    source = add_source(conn, folder)
    first_id = _insert_document(
        conn, source_id=source.id, file_path="/docs/a.pdf", file_type="pdf", status="indexed"
    )
    logical_document_id = conn.execute(
        "SELECT document_id FROM document_index WHERE id = ?", (first_id,)
    ).fetchone()["document_id"]
    second_id = _insert_document(
        conn,
        document_id=logical_document_id,
        source_id=source.id,
        file_path="/docs/b.pdf",
        file_type="pdf",
        status="indexed",
    )

    _refresh_document_paths(conn, {logical_document_id})
    assert _primary_path(conn, logical_document_id) == "/docs/a.pdf"

    conn.execute("UPDATE document_index SET status = 'removed' WHERE id = ?", (first_id,))
    _refresh_document_paths(conn, {logical_document_id})
    assert _primary_path(conn, logical_document_id) == "/docs/b.pdf"

    conn.execute("UPDATE document_index SET status = 'removed' WHERE id = ?", (second_id,))
    _refresh_document_paths(conn, {logical_document_id})
    assert _primary_path(conn, logical_document_id) is None


def _primary_path(conn: sqlite3.Connection, document_id: int) -> str | None:
    row = conn.execute("SELECT file_path FROM documents WHERE id = ?", (document_id,)).fetchone()
    return row["file_path"]
