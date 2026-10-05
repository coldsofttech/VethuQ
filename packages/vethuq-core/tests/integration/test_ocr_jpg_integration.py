"""JPG images read with the real PaddleOCR models, checked against `expected.json`.

`fixtures/en/jpg/expected.json` says what each image must come out as: its status and, for its
one page, the OCR confidence it must reach and phrases it must contain.
`scripts/dev/generate_integration_expected.py --dir <this folder>` regenerates it.

Every JPG is read with the real PaddleOCR models, so these cases run only when `VETHUQ_REAL_OCR=1`
(set by `.github/workflows/integration.yml`, which downloads the models first). Locally:

    uv run vethuq ocr models download --lang en
    VETHUQ_REAL_OCR=1 uv run pytest -m integration packages/vethuq-core/tests/integration
"""

import sqlite3
from pathlib import Path

import expected_support as expected
import pytest
from vethuq_core.ocr import Ocr
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "en" / "jpg"
EXPECTED = expected.load(FIXTURES_DIR)
LANGUAGE = EXPECTED["language"]

pytestmark = [pytest.mark.integration, pytest.mark.lang_en, pytest.mark.type_jpg]

_ENTRIES = EXPECTED["files"]


class TestFixtures:
    def test_every_fixture_has_an_expected_entry(self):
        on_disk = {path.name for path in FIXTURES_DIR.glob("*.jpg")}

        assert on_disk == {entry["file"] for entry in _ENTRIES}

    def test_the_expected_file_names_its_language_and_type(self):
        assert EXPECTED["language"] == "en"
        assert EXPECTED["file_type"] == "jpg"


class TestPngIntegration:
    @pytest.mark.parametrize("entry", [expected.case(e) for e in _ENTRIES])
    def test_the_image_is_indexed_as_expected(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        fixture = FIXTURES_DIR / entry["file"]
        jpg_path = tmp_path / "scan.jpg"
        jpg_path.write_bytes(fixture.read_bytes())
        source = Sources.add(storage, jpg_path, languages=LANGUAGE)

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(jpg_path.resolve()),)
        ).fetchone()
        assert doc["status"] == entry["status"], doc["error_message"]
        assert doc["file_type"] == "image"
        assert doc["file_size_bytes"] == fixture.stat().st_size

        pages = conn.execute(
            "SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)
        ).fetchall()
        assert len(pages) == entry["page_count"]
        wanted = entry["pages"]["1"]
        page = pages[0]
        assert page["language"] in (None, "", LANGUAGE)
        if "min_confidence" in wanted:
            assert page["confidence"] >= wanted["min_confidence"]
        for phrase in wanted["contains"]:
            assert expected.contains(page["ocr_text"], phrase, wanted["source"]), phrase
