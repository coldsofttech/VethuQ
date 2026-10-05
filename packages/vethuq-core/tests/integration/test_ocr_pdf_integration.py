"""PDFs read for real: native text, scans and mixed pages, checked against `expected.json`.

`fixtures/en/pdf/expected.json` says what each file must come out as: its status, page count and,
per page, where the text came from (`native`, `ocr` or `mixed`), the OCR confidence it must reach
and phrases it must contain. `scripts/dev/generate_integration_expected.py` regenerates it.

A file with only native pages needs no OCR, so those cases run anywhere. A file with a scanned or
mixed page is read with the real PaddleOCR models: those cases run only when `VETHUQ_REAL_OCR=1`
(set by `.github/workflows/integration.yml`, which downloads the models first). Locally:

    uv run vethuq ocr models download --lang en
    VETHUQ_REAL_OCR=1 uv run pytest -m integration packages/vethuq-core/tests/integration
"""

import json
import os
import sqlite3
import unicodedata
from pathlib import Path
from unittest.mock import patch

import pytest
from vethuq_core.ocr import Ocr
from vethuq_core.ocr.engines import Engines
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "en" / "pdf"
EXPECTED = json.loads((FIXTURES_DIR / "expected.json").read_text(encoding="utf-8"))
LANGUAGE = EXPECTED["language"]

# What fraction of a phrase's words OCR must have read for the phrase to count as found. OCR is
# not byte-exact (a stray character here and there), so a scanned page is matched by its words.
OCR_WORD_SHARE = 0.8

pytestmark = [pytest.mark.integration, pytest.mark.lang_en, pytest.mark.type_pdf]

_ENTRIES = EXPECTED["files"]
_REAL_OCR = os.environ.get("VETHUQ_REAL_OCR") == "1"


def _needs_ocr(entry: dict) -> bool:
    return any(page["source"] != "native" for page in entry["pages"].values())


def _case(entry: dict):
    marks = []
    if _needs_ocr(entry) and not _REAL_OCR:
        marks.append(
            pytest.mark.skip(
                reason="reads with real PaddleOCR: set VETHUQ_REAL_OCR=1 and the models"
            )
        )
    return pytest.param(entry, id=entry["file"][:2], marks=marks)


def _words(text: str) -> list[str]:
    return unicodedata.normalize("NFC", text).casefold().split()


def _contains(page_text: str, phrase: str, source: str) -> bool:
    """Native text must hold the phrase as written (whitespace aside); OCR text, most of its
    words."""
    page = " ".join(unicodedata.normalize("NFC", page_text).split())
    wanted = " ".join(unicodedata.normalize("NFC", phrase).split())
    if source == "native":
        return wanted in page
    have = set(_words(page_text))
    words = _words(phrase)
    return sum(word in have for word in words) / len(words) >= OCR_WORD_SHARE


def _index(storage: Storage, tmp_path: Path, name: str):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes((FIXTURES_DIR / name).read_bytes())
    source = Sources.add(storage, pdf_path, languages=LANGUAGE)
    Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
    return pdf_path


class TestFixtures:
    def test_every_fixture_has_an_expected_entry(self):
        on_disk = {path.name for path in FIXTURES_DIR.glob("*.pdf")}

        assert on_disk == {entry["file"] for entry in _ENTRIES}

    def test_the_expected_file_names_its_language_and_type(self):
        assert EXPECTED["language"] == "en"
        assert EXPECTED["file_type"] == "pdf"


class TestPdfIntegration:
    @pytest.mark.parametrize("entry", [_case(e) for e in _ENTRIES])
    def test_the_file_is_indexed_as_expected(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        pdf_path = _index(storage, tmp_path, entry["file"])

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(pdf_path.resolve()),)
        ).fetchone()
        assert doc["status"] == entry["status"], doc["error_message"]
        if entry["status"] != "indexed":
            assert doc["error_message"]
            assert conn.execute("SELECT COUNT(*) FROM pdf_pages").fetchone()[0] == 0
            return

        pages = {
            page["page_number"]: page
            for page in conn.execute(
                "SELECT * FROM pdf_pages WHERE document_id = ?", (doc["id"],)
            ).fetchall()
        }
        assert len(pages) == entry["page_count"]
        for number, expected in entry["pages"].items():
            page = pages[int(number)]
            assert page["source"] == expected["source"], f"page {number}"
            assert page["language"] in (None, "", LANGUAGE)
            if "min_confidence" in expected:
                assert page["confidence"] >= expected["min_confidence"], f"page {number}"
            for phrase in expected["contains"]:
                assert _contains(page["ocr_text"], phrase, expected["source"]), (
                    f"page {number}: {phrase!r}"
                )

    @pytest.mark.parametrize("entry", [_case(e) for e in _ENTRIES if not _needs_ocr(e)])
    def test_native_files_never_start_the_ocr_engine(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        if entry["status"] != "indexed":
            pytest.skip("not an indexed file")

        with patch("vethuq_core.ocr.engines.Engines.get", wraps=Engines.get) as spy:
            _index(storage, tmp_path, entry["file"])

        spy.assert_not_called()
        confidences = [row[0] for row in conn.execute("SELECT confidence FROM pdf_pages")]
        assert confidences == [pytest.approx(1.0)] * len(confidences)

    @pytest.mark.parametrize("entry", [_case(e) for e in _ENTRIES if _needs_ocr(e)])
    def test_scanned_and_mixed_files_are_read_by_the_ocr_engine(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        _index(storage, tmp_path, entry["file"])

        scanned = [
            row["ocr_text"]
            for row in conn.execute("SELECT ocr_text, source FROM pdf_pages")
            if row["source"] != "native"
        ]
        assert scanned
        assert all(text.strip() for text in scanned)
