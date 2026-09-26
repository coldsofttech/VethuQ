import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.db import connect
from vethuq_core.ocr import _is_native_text, _resolve_device, run_ocr
from vethuq_core.settings import set_gpu_enabled
from vethuq_core.sources import add_source

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
