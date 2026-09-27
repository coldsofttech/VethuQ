import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.db import connect
from vethuq_core.ocr import _has_content_changed, _is_native_text, _resolve_device, run_ocr
from vethuq_core.settings import set_gpu_enabled
from vethuq_core.sources import add_source, purge_expired_removed_documents

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pdf"


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "vethuq.db"
    connection = connect(db_path)
    yield connection
    connection.close()


def _fake_ocr_result(text: str = "hello world", score: float = 0.95):
    return [{"rec_texts": [text], "rec_scores": [score]}]


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_indexes_image_file(mock_get_engine, conn: sqlite3.Connection, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake png bytes")
    source = add_source(conn, image_path)

    run_ocr(conn, source)

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "indexed"
    assert doc["file_type"] == "image"

    page = conn.execute("SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)).fetchone()
    assert page["ocr_text"] == "hello world"
    assert page["confidence"] == pytest.approx(0.95)

    updated_source = conn.execute(
        "SELECT status FROM sources WHERE id = ?", (source.id,)
    ).fetchone()
    assert updated_source["status"] == "indexed"
    assert doc["file_size_bytes"] == image_path.stat().st_size


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_links_duplicate_content_without_rerunning_ocr(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"identical bytes")
    (folder / "b.png").write_bytes(b"identical bytes")
    source = add_source(conn, folder)

    run_ocr(conn, source)

    assert engine.predict.call_count == 1

    docs = conn.execute("SELECT * FROM document_index").fetchall()
    assert len(docs) == 2
    originals = [doc for doc in docs if doc["duplicate_of_id"] is None]
    duplicates = [doc for doc in docs if doc["duplicate_of_id"] is not None]
    assert len(originals) == 1
    assert len(duplicates) == 1
    original, duplicate = originals[0], duplicates[0]

    assert original["status"] == "indexed"
    assert duplicate["status"] == "indexed"
    assert duplicate["duplicate_of_id"] == original["id"]
    assert original["checksum"] == duplicate["checksum"]

    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM image_pages WHERE document_id = ?", (duplicate["id"],)
        ).fetchone()["n"]
        == 0
    )


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_promotes_duplicate_when_original_is_modified(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("shared content")
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    file1 = folder / "a.png"
    file2 = folder / "b.png"
    file1.write_bytes(b"identical bytes")
    file2.write_bytes(b"identical bytes")
    source = add_source(conn, folder)

    run_ocr(conn, source)

    doc1 = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(file1.resolve()),)
    ).fetchone()
    doc2 = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(file2.resolve()),)
    ).fetchone()
    assert doc1["duplicate_of_id"] is None
    assert doc2["duplicate_of_id"] == doc1["id"]

    # file1 (the original) gets modified; file2 (the duplicate) is untouched.
    new_mtime = file1.stat().st_mtime + 5
    file1.write_bytes(b"totally different, longer content now")
    os.utime(file1, (new_mtime, new_mtime))
    engine.predict.return_value = _fake_ocr_result("new content for file1")

    second_run = run_ocr(conn, source, only_new_files=True)

    # Only file1 needed reprocessing - file2's own bytes never changed.
    assert second_run == [str(file1.resolve())]

    doc1_after = conn.execute("SELECT * FROM document_index WHERE id = ?", (doc1["id"],)).fetchone()
    doc2_after = conn.execute("SELECT * FROM document_index WHERE id = ?", (doc2["id"],)).fetchone()

    # file2 is promoted back to being its own original rather than silently
    # inheriting file1's new (unrelated) OCR text.
    assert doc2_after["duplicate_of_id"] is None
    assert doc1_after["duplicate_of_id"] is None

    page1 = conn.execute(
        "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc1["id"],)
    ).fetchone()
    assert page1["ocr_text"] == "new content for file1"

    page2 = conn.execute(
        "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc2["id"],)
    ).fetchone()
    assert page2["ocr_text"] == "shared content"


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_updates_processing_metrics_on_success(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result(score=0.8)
    mock_get_engine.return_value = engine

    first = tmp_path / "first.png"
    first.write_bytes(b"fake png bytes")
    run_ocr(conn, add_source(conn, first))

    metrics = conn.execute("SELECT * FROM processing_metrics WHERE file_type = 'image'").fetchone()
    assert metrics["document_count"] == 1

    confidence = conn.execute(
        "SELECT * FROM confidence_metrics WHERE file_type = 'image' AND process_type = 'ocr'"
    ).fetchone()
    assert confidence["page_count"] == 1
    assert confidence["avg_confidence"] == pytest.approx(0.8)

    engine.predict.return_value = _fake_ocr_result(score=0.6)
    second = tmp_path / "second.png"
    second.write_bytes(b"more fake png bytes")
    run_ocr(conn, add_source(conn, second))

    metrics = conn.execute("SELECT * FROM processing_metrics WHERE file_type = 'image'").fetchone()
    assert metrics["document_count"] == 2

    confidence = conn.execute(
        "SELECT * FROM confidence_metrics WHERE file_type = 'image' AND process_type = 'ocr'"
    ).fetchone()
    assert confidence["page_count"] == 2
    assert confidence["avg_confidence"] == pytest.approx(0.7)


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_does_not_update_processing_metrics_on_error(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.side_effect = RuntimeError("ocr blew up")
    mock_get_engine.return_value = engine

    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake png bytes")
    run_ocr(conn, add_source(conn, image_path))

    assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None
    assert conn.execute("SELECT * FROM confidence_metrics").fetchone() is None


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_skips_unsupported_files(mock_get_engine, conn: sqlite3.Connection, tmp_path):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "notes.txt").write_text("not ocr-able")
    (folder / "scan.jpg").write_bytes(b"fake jpg bytes")
    source = add_source(conn, folder)

    run_ocr(conn, source)

    docs = conn.execute("SELECT file_path FROM document_index").fetchall()
    assert len(docs) == 1
    assert docs[0]["file_path"].endswith("scan.jpg")


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_records_error_without_aborting(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.side_effect = RuntimeError("ocr blew up")
    mock_get_engine.return_value = engine

    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake png bytes")
    source = add_source(conn, image_path)

    run_ocr(conn, source)

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "error"
    assert "ocr blew up" in doc["error_message"]

    updated_source = conn.execute(
        "SELECT status FROM sources WHERE id = ?", (source.id,)
    ).fetchone()
    assert updated_source["status"] == "error"


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_rerun_replaces_stale_page_rows(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("first pass")
    mock_get_engine.return_value = engine

    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake png bytes")
    source = add_source(conn, image_path)
    run_ocr(conn, source)

    engine.predict.return_value = _fake_ocr_result("second pass")
    run_ocr(conn, source)

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
    ).fetchone()
    pages = conn.execute("SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)).fetchall()
    assert len(pages) == 1
    assert pages[0]["ocr_text"] == "second pass"


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_only_new_files_skips_already_indexed(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("first file")
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "first.png").write_bytes(b"fake png bytes")
    source = add_source(conn, folder)

    first_run = run_ocr(conn, source)
    assert first_run == [str((folder / "first.png").resolve())]

    # A new file shows up in the folder after the source is already indexed.
    (folder / "second.png").write_bytes(b"fake png bytes")
    engine.predict.return_value = _fake_ocr_result("second file")

    second_run = run_ocr(conn, source, only_new_files=True)

    assert second_run == [str((folder / "second.png").resolve())]

    docs = {
        row["file_path"]: row["status"]
        for row in conn.execute("SELECT file_path, status FROM document_index")
    }
    assert docs[str((folder / "first.png").resolve())] == "indexed"
    assert docs[str((folder / "second.png").resolve())] == "indexed"


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_only_new_files_reindexes_modified_file(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("original content")
    mock_get_engine.return_value = engine

    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"original bytes")
    source = add_source(conn, image_path)

    run_ocr(conn, source)
    doc = conn.execute(
        "SELECT id FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
    ).fetchone()

    # Edit the file's content and bump its mtime so the fast path notices.
    new_mtime = image_path.stat().st_mtime + 5
    image_path.write_bytes(b"changed bytes, a different length than before")
    os.utime(image_path, (new_mtime, new_mtime))
    engine.predict.return_value = _fake_ocr_result("updated content")

    second_run = run_ocr(conn, source, only_new_files=True)

    assert second_run == [str(image_path.resolve())]
    page = conn.execute(
        "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc["id"],)
    ).fetchone()
    assert page["ocr_text"] == "updated content"


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_only_new_files_skips_unchanged_file_without_rehashing(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("original content")
    mock_get_engine.return_value = engine

    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"original bytes")
    source = add_source(conn, image_path)

    run_ocr(conn, source)

    with patch("vethuq_core.ocr._compute_checksum") as mock_checksum:
        second_run = run_ocr(conn, source, only_new_files=True)
        mock_checksum.assert_not_called()

    assert second_run == []


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_only_new_files_detects_plain_rename(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("original text")
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    old_path = folder / "scan.png"
    old_path.write_bytes(b"fake png bytes")
    source = add_source(conn, folder)

    run_ocr(conn, source)
    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(old_path.resolve()),)
    ).fetchone()

    new_path = folder / "renamed.png"
    old_path.rename(new_path)

    second_run = run_ocr(conn, source, only_new_files=True)

    assert engine.predict.call_count == 1  # no re-OCR for a plain rename
    assert second_run == [str(new_path.resolve())]

    updated = conn.execute("SELECT * FROM document_index WHERE id = ?", (doc["id"],)).fetchone()
    assert updated["file_path"] == str(new_path.resolve())
    assert updated["status"] == "indexed"
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM document_index WHERE file_path = ?",
            (str(old_path.resolve()),),
        ).fetchone()["n"]
        == 0
    )


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_only_new_files_marks_missing_file_removed(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result()
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    image_path = folder / "scan.png"
    image_path.write_bytes(b"fake png bytes")
    source = add_source(conn, folder)

    run_ocr(conn, source)
    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(image_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "indexed"

    image_path.unlink()
    second_run = run_ocr(conn, source, only_new_files=True)

    assert second_run == []
    updated = conn.execute(
        "SELECT status, removed_at FROM document_index WHERE id = ?", (doc["id"],)
    ).fetchone()
    assert updated["status"] == "removed"
    assert updated["removed_at"] is not None


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_handles_duplicate_original_deleted_and_duplicate_renamed(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("shared content")
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    file_a = folder / "a.png"
    file_b = folder / "b.png"
    file_a.write_bytes(b"identical bytes")
    file_b.write_bytes(b"identical bytes")
    source = add_source(conn, folder)

    run_ocr(conn, source)

    doc_a = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(file_a.resolve()),)
    ).fetchone()
    doc_b = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(file_b.resolve()),)
    ).fetchone()
    assert doc_a["duplicate_of_id"] is None
    assert doc_b["duplicate_of_id"] == doc_a["id"]

    # The original (file_a) is deleted outright; the duplicate (file_b) is
    # renamed rather than touched.
    file_c = folder / "c.png"
    file_a.unlink()
    file_b.rename(file_c)

    second_run = run_ocr(conn, source, only_new_files=True)

    # No OCR needed - the content at file_c already matches an indexed row.
    assert engine.predict.call_count == 1
    assert second_run == [str(file_c.resolve())]

    rows_by_id = {
        row["id"]: row
        for row in conn.execute(
            "SELECT * FROM document_index WHERE id IN (?, ?)", (doc_a["id"], doc_b["id"])
        )
    }
    survivor = rows_by_id[doc_a["id"]]
    gone = rows_by_id[doc_b["id"]]

    assert survivor["file_path"] == str(file_c.resolve())
    assert survivor["status"] == "indexed"
    assert survivor["duplicate_of_id"] is None
    assert gone["status"] == "removed"
    assert gone["removed_at"] is not None

    page = conn.execute(
        "SELECT ocr_text FROM image_pages WHERE document_id = ?", (survivor["id"],)
    ).fetchone()
    assert page["ocr_text"] == "shared content"


@patch("vethuq_core.ocr._get_engine")
def test_purge_promotes_duplicate_when_original_document_is_removed(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("shared content")
    mock_get_engine.return_value = engine

    folder = tmp_path / "docs"
    folder.mkdir()
    file_a = folder / "a.png"
    file_b = folder / "b.png"
    file_a.write_bytes(b"identical bytes")
    file_b.write_bytes(b"identical bytes")
    source = add_source(conn, folder)

    run_ocr(conn, source)

    doc_a = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(file_a.resolve()),)
    ).fetchone()
    doc_b = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(file_b.resolve()),)
    ).fetchone()
    assert doc_b["duplicate_of_id"] == doc_a["id"]

    # file_a (the original) is deleted outright, with nothing to rename it to.
    file_a.unlink()
    run_ocr(conn, source, only_new_files=True)

    removed = conn.execute(
        "SELECT status, removed_at FROM document_index WHERE id = ?", (doc_a["id"],)
    ).fetchone()
    assert removed["status"] == "removed"
    assert removed["removed_at"] is not None

    purge_expired_removed_documents(conn, retention_minutes=-1)

    survivor = conn.execute("SELECT * FROM document_index WHERE id = ?", (doc_b["id"],)).fetchone()
    assert survivor["duplicate_of_id"] is None
    assert survivor["status"] == "indexed"

    page = conn.execute(
        "SELECT ocr_text FROM image_pages WHERE document_id = ?", (doc_b["id"],)
    ).fetchone()
    assert page["ocr_text"] == "shared content"

    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM document_index WHERE id = ?", (doc_a["id"],)
        ).fetchone()["n"]
        == 0
    )


def test_has_content_changed_skips_hash_when_mtime_and_size_unchanged(tmp_path):
    file_path = tmp_path / "scan.png"
    file_path.write_bytes(b"unchanged")
    stat = file_path.stat()
    existing = {
        "mtime": stat.st_mtime,
        "file_size_bytes": stat.st_size,
        "checksum": "irrelevant",
    }

    with patch("vethuq_core.ocr._compute_checksum") as mock_checksum:
        assert _has_content_changed(file_path, existing) is False
        mock_checksum.assert_not_called()


def test_has_content_changed_true_when_checksum_differs_despite_same_size(tmp_path):
    file_path = tmp_path / "scan.png"
    file_path.write_bytes(b"aaaaaaaaa")
    stat = file_path.stat()
    existing = {
        "mtime": stat.st_mtime - 10,
        "file_size_bytes": stat.st_size,
        "checksum": "not-the-real-checksum",
    }

    assert _has_content_changed(file_path, existing) is True


def test_resolve_device_defaults_to_cpu(conn: sqlite3.Connection):
    assert _resolve_device(conn) == "cpu"


def test_resolve_device_uses_gpu_when_enabled_and_available(conn: sqlite3.Connection):
    mock_paddle = MagicMock()
    mock_paddle.device.is_compiled_with_cuda.return_value = True
    mock_paddle.device.cuda.device_count.return_value = 1
    set_gpu_enabled(conn, True)

    with patch.dict(sys.modules, {"paddle": mock_paddle}):
        assert _resolve_device(conn) == "gpu"


def test_resolve_device_falls_back_to_cpu_when_enabled_but_unsupported(
    conn: sqlite3.Connection,
):
    mock_paddle = MagicMock()
    mock_paddle.device.is_compiled_with_cuda.return_value = False
    set_gpu_enabled(conn, True)

    with patch.dict(sys.modules, {"paddle": mock_paddle}):
        assert _resolve_device(conn) == "cpu"


def test_is_native_text_threshold():
    assert not _is_native_text("")
    assert not _is_native_text("p.3")
    assert not _is_native_text("a-long-single-token-with-no-spaces-at-all")
    assert _is_native_text("This is a real paragraph of page content.")


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_digital_pdf_skips_engine_entirely(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    pdf_path = tmp_path / "digital.pdf"
    pdf_path.write_bytes((FIXTURES_DIR / "03_Digital Formal Letter.pdf").read_bytes())
    source = add_source(conn, pdf_path)

    run_ocr(conn, source)

    mock_get_engine.assert_not_called()

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(pdf_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "indexed"

    page = conn.execute("SELECT * FROM pdf_pages WHERE document_id = ?", (doc["id"],)).fetchone()
    assert page["source"] == "native"
    assert page["confidence"] == pytest.approx(1.0)
    assert len(page["ocr_text"]) > 0


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_scanned_pdf_runs_full_page_ocr(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("scanned page text")
    mock_get_engine.return_value = engine

    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes((FIXTURES_DIR / "05_Scanned Document.pdf").read_bytes())
    source = add_source(conn, pdf_path)

    run_ocr(conn, source)

    engine.predict.assert_called_once()

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(pdf_path.resolve()),)
    ).fetchone()
    page = conn.execute("SELECT * FROM pdf_pages WHERE document_id = ?", (doc["id"],)).fetchone()
    assert page["source"] == "ocr"
    assert page["ocr_text"] == "scanned page text"


@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_mixed_pdf_keeps_native_text_and_ocrs_image_region(
    mock_get_engine, conn: sqlite3.Connection, tmp_path
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("banner region text")
    mock_get_engine.return_value = engine

    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(
        (FIXTURES_DIR / "04_Digital Bilingual Travel & Cultural Guide.pdf").read_bytes()
    )
    source = add_source(conn, pdf_path)

    run_ocr(conn, source)

    engine.predict.assert_called_once()

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(pdf_path.resolve()),)
    ).fetchone()
    page = conn.execute("SELECT * FROM pdf_pages WHERE document_id = ?", (doc["id"],)).fetchone()
    assert page["source"] == "mixed"
    assert "Discover Andhra Pradesh" in page["ocr_text"]
    assert "banner region text" in page["ocr_text"]
