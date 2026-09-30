import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from vethuq_core.db import connect
from vethuq_core.ocr import run_ocr
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


# (fixture file, expected pdf_pages.source, expected page count, expected engine calls,
#  {page number: phrase that page's text must contain}). Scanned fixtures (09, 11) have no
#  native text, so their phrase is the mocked OCR output.
_PDF_CASES = [
    (
        "06_Digital Structured Business Documents.pdf",
        "native",
        3,
        0,
        {
            1: "NEXUS LOGISTICS SOLUTIONS",
            2: "FINANCIAL SUMMARY Q3 2026",
            3: "EQUIPMENT SERVICE & MAINTENANCE FORM",
        },
    ),
    (
        "07_Digital Academic Journal Article.pdf",
        "native",
        2,
        0,
        {
            1: "Distributed Neural Optimization in Asynchronous Multi-Agent Systems",
            2: "RESULTS & ANALYSIS",
        },
    ),
    (
        "08_Digital Patient Registration & History Form.pdf",
        "native",
        1,
        0,
        {1: "METRO HEALTH MEDICAL CENTER"},
    ),
    (
        "09_Digital Patient Registration & History Form.pdf",
        "ocr",
        1,
        1,
        {1: "ocr text"},
    ),
    (
        "10_Digital Document Skew & Rotation Analysis Report.pdf",
        "native",
        1,
        0,
        {1: "DOCUMENT ROTATION & SKEW ANALYSIS"},
    ),
    (
        "11_Digital Archival Intelligence Briefing - Project Aurora.pdf",
        "ocr",
        1,
        1,
        {1: "ocr text"},
    ),
    (
        "12_Digital Programmatic PDF Edge Cases & Stress Test.pdf",
        "native",
        3,
        0,
        {
            1: "PDF ENGINE EDGE-CASE DIAGNOSTIC REPORT",
            2: "THIS PAGE INTENTIONALLY LEFT BLANK",
            3: "DIAGNOSTIC TEST RESULTS",
        },
    ),
    (
        "13_Digital 50 Page Guide.pdf",
        "native",
        50,
        0,
        {
            1: "ENTERPRISE SYSTEMS ARCHITECTURE & ENGINEERING",
            50: "Regulatory Compliance & Security Logging",
        },
    ),
    (
        "14_Digital A3 Executive Analytics & Systems Dashboard.pdf",
        "native",
        1,
        0,
        {1: "Global Cloud Infrastructure & Operational Overview"},
    ),
    (
        "15_Digital Letter Corporate Performance & Strategic Overview.pdf",
        "native",
        1,
        0,
        {1: "EXECUTIVE STRATEGIC REPORT"},
    ),
    (
        "16_Digital Receipt Thermal Receipt Reference.pdf",
        "native",
        1,
        0,
        {1: "METRO PROVISIONS"},
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fixture_name", "source_type", "page_count", "engine_calls", "expected_text"),
    _PDF_CASES,
    ids=[case[0][:2] for case in _PDF_CASES],
)
@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_fixture_pdf_indexes_expected_pages(
    mock_get_engine,
    fixture_name,
    source_type,
    page_count,
    engine_calls,
    expected_text,
    conn: sqlite3.Connection,
    tmp_path,
):
    engine = MagicMock()
    engine.predict.return_value = _fake_ocr_result("ocr text")
    mock_get_engine.return_value = engine

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes((FIXTURES_DIR / fixture_name).read_bytes())
    source = add_source(conn, pdf_path)

    run_ocr(conn, source)

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(pdf_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "indexed"

    pages = conn.execute("SELECT * FROM pdf_pages WHERE document_id = ?", (doc["id"],)).fetchall()
    assert len(pages) == page_count
    assert {page["source"] for page in pages} == {source_type}
    assert engine.predict.call_count == engine_calls

    text_by_page = {page["page_number"]: " ".join(page["ocr_text"].split()) for page in pages}
    for page_number, phrase in expected_text.items():
        assert phrase in text_by_page[page_number]


@pytest.mark.integration
@pytest.mark.parametrize(
    "fixture_name",
    [
        "17_Digital Protected File (Pass - Abc123).pdf",
        "18_Digital Corrupted.pdf",
    ],
    ids=["protected", "corrupted"],
)
@patch("vethuq_core.ocr._get_engine")
def test_run_ocr_unreadable_pdf_records_error_without_aborting(
    mock_get_engine, fixture_name, conn: sqlite3.Connection, tmp_path
):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes((FIXTURES_DIR / fixture_name).read_bytes())
    source = add_source(conn, pdf_path)

    run_ocr(conn, source)

    mock_get_engine.return_value.predict.assert_not_called()

    doc = conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(pdf_path.resolve()),)
    ).fetchone()
    assert doc["status"] == "error"
    assert doc["error_message"]
    assert conn.execute("SELECT COUNT(*) FROM pdf_pages").fetchone()[0] == 0
