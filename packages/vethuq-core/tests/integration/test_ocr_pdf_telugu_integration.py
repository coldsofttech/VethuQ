"""Telugu PDFs read for real: native text, scans and mixed English/Telugu, per `expected.json`.

`fixtures/te/pdf/expected.json` says what each file must come out as: the languages its source is
read in, its status and page count and, per page, where the text came from, the languages it was
read in, the OCR confidence it must reach and phrases it must contain; and `searches` that must or
must not find the file. The files are made by `scripts/dev/generate_telugu_fixtures.py` and the
expectations by `scripts/dev/generate_integration_expected.py --lang te`.

A file with only native pages needs no OCR (and no OCR model), so those cases run anywhere. A file
with a scanned page is read with the real PaddleOCR models, English and Telugu: those cases run only
when `VETHUQ_REAL_OCR=1` (set by `.github/workflows/integration.yml`, which downloads the models
first). Locally:

    uv run vethuq ocr models download --lang en --lang te
    VETHUQ_REAL_OCR=1 uv run pytest -m "integration and lang_te" \\
        packages/vethuq-core/tests/integration
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import expected_support as expected
import pytest
from vethuq_core.ocr import Ocr
from vethuq_core.ocr.engines import Engines
from vethuq_core.search import Export, Search
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Sources
from vethuq_core.stats import Confidence
from vethuq_core.storage import Storage

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "te" / "pdf"
EXPECTED = expected.load(FIXTURES_DIR)
LANGUAGE = EXPECTED["language"]

pytestmark = [pytest.mark.integration, pytest.mark.lang_te, pytest.mark.type_pdf]

_ENTRIES = EXPECTED["files"]
_BY_NAME = {entry["file"]: entry for entry in _ENTRIES}
_INDEXED = [e for e in _ENTRIES if e["status"] == "indexed"]
_NATIVE = [e for e in _INDEXED if not expected.needs_ocr(e)]
_SEARCHED = [e for e in _INDEXED if e.get("searches")]


def _read_in(page) -> set[str]:
    langs = {part for part in (page["ocr_langs"] or "").split(",") if part}
    if page["language"]:
        langs.add(page["language"])
    return langs or {"en"}


def _index_file(storage: Storage, tmp_path: Path, entry: dict) -> Path:
    """Index one fixture as its own source, the way the entry says (languages, OCR engine)."""
    if entry.get("engine"):
        OcrSettings.set_engine(storage, entry["engine"])
    folder = tmp_path / "docs"
    folder.mkdir(exist_ok=True)
    pdf_path = folder / entry["file"]
    pdf_path.write_bytes((FIXTURES_DIR / entry["file"]).read_bytes())
    source = Sources.add(storage, pdf_path, languages=entry.get("languages", LANGUAGE))
    Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
    return pdf_path


class TestFixtures:
    def test_every_fixture_has_an_expected_entry(self):
        on_disk = {path.name for path in FIXTURES_DIR.glob("*.pdf")}

        assert on_disk == {entry["file"] for entry in _ENTRIES}

    def test_the_expected_file_names_its_language_and_type(self):
        assert EXPECTED["language"] == "te"
        assert EXPECTED["file_type"] == "pdf"

    def test_a_scan_has_no_text_layer_and_a_native_file_has(self):
        import pymupdf

        for entry in _INDEXED:
            with pymupdf.open(FIXTURES_DIR / entry["file"]) as doc:
                has_text = [bool(page.get_text().strip()) for page in doc]
            native = [page["source"] == "native" for page in entry["pages"].values()]
            assert has_text == native, entry["file"]


class TestTeluguPdfIntegration:
    @pytest.mark.parametrize("entry", [expected.case(e) for e in _ENTRIES])
    def test_the_file_is_indexed_as_expected(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        pdf_path = _index_file(storage, tmp_path, entry)

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(pdf_path.resolve()),)
        ).fetchone()
        assert doc["status"] == entry["status"], doc["error_message"]
        if entry["status"] != "indexed":
            assert doc["error_message"]
            assert conn.execute("SELECT COUNT(*) FROM pdf_pages").fetchone()[0] == 0
            return

        assert Path(doc["file_path"]).name == entry["file"]
        pages = {
            page["page_number"]: page
            for page in conn.execute(
                "SELECT * FROM pdf_pages WHERE document_id = ?", (doc["id"],)
            ).fetchall()
        }
        assert len(pages) == entry["page_count"]
        for number, want in entry["pages"].items():
            page = pages[int(number)]
            assert page["source"] == want["source"], f"page {number}"
            assert set(want["read_in"]) <= _read_in(page), f"page {number}: {_read_in(page)}"
            if "min_confidence" in want:
                assert page["confidence"] >= want["min_confidence"], f"page {number}"
            for phrase in want["contains"]:
                assert expected.contains(page["ocr_text"], phrase, want["source"]), (
                    f"page {number}: {phrase!r}"
                )

    @pytest.mark.parametrize("entry", [expected.case(e) for e in _SEARCHED])
    def test_the_searches_find_what_they_should(self, entry, storage: Storage, tmp_path):
        _index_file(storage, tmp_path, entry)

        for search in entry["searches"]:
            found = Search.indexed_content(
                storage,
                search["query"],
                engine=search.get("engine", "like"),
                languages=search.get("lang"),
                unicode=search.get("unicode"),
            )
            assert bool(found) is search.get("found", True), search

    @pytest.mark.xfail(
        strict=True, reason="known gap: a Telugu query typed without its zero-width joiner"
    )
    @pytest.mark.parametrize("entry", [expected.case(e) for e in _INDEXED if e.get("known_gaps")])
    def test_known_gaps(self, entry, storage: Storage, tmp_path):
        """Searches that should find the file but do not yet. `strict`: when one starts to work
        this fails, as the cue to move it to `searches` in `expected.json`."""
        _index_file(storage, tmp_path, entry)

        for gap in entry["known_gaps"]:
            found = Search.indexed_content(storage, gap["query"], engine=gap["engine"])
            assert found, gap

    @pytest.mark.parametrize("entry", [expected.case(e) for e in _NATIVE])
    def test_native_files_never_start_the_ocr_engine(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        with patch("vethuq_core.ocr.engines.Engines.get", wraps=Engines.get) as spy:
            _index_file(storage, tmp_path, entry)

        spy.assert_not_called()
        confidences = [row[0] for row in conn.execute("SELECT confidence FROM pdf_pages")]
        assert confidences == [pytest.approx(1.0)] * len(confidences)

    @pytest.mark.parametrize("entry", [expected.case(e) for e in _ENTRIES if expected.needs_ocr(e)])
    def test_scanned_files_are_read_by_the_ocr_engine(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        _index_file(storage, tmp_path, entry)

        scanned = [
            row["ocr_text"]
            for row in conn.execute("SELECT ocr_text, source FROM pdf_pages")
            if row["source"] != "native"
        ]
        assert scanned
        assert all(text.strip() for text in scanned)


class TestAcrossFiles:
    def test_a_duplicate_shares_the_originals_pages_and_language(self, storage: Storage, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        for name in ("01_Telugu_Native_Letter.pdf", "18_Telugu_Duplicate_Of_01.pdf"):
            (folder / name).write_bytes((FIXTURES_DIR / name).read_bytes())
        source = Sources.add(storage, folder, languages="te")

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        found = Search.indexed_content(storage, "సాహిత్య", engine="like", languages="te")
        assert {m.file_name for m in found} == {
            "01_Telugu_Native_Letter.pdf",
            "18_Telugu_Duplicate_Of_01.pdf",
        }
        assert Search.indexed_content(storage, "సాహిత్య", engine="like", languages="en") == []

    def test_statistics_are_kept_under_telugu(self, storage: Storage, tmp_path):
        _index_file(storage, tmp_path, _BY_NAME["01_Telugu_Native_Letter.pdf"])

        metrics = Confidence.get_metrics(storage)

        assert {m.language for m in metrics} == {"te"}
        assert metrics[0].page_count == 1
        assert metrics[0].avg_confidence == pytest.approx(1.0)

    def test_the_language_filter_separates_english_and_telugu_pages(
        self, storage: Storage, tmp_path
    ):
        _index_file(storage, tmp_path, _BY_NAME["04_Telugu_Native_Multipage.pdf"])

        telugu = Search.indexed_content(storage, "river", engine="like", languages="te")
        english = Search.indexed_content(storage, "river", engine="like", languages="en")

        assert {m.page_number for m in english} == {2}
        assert telugu == []
        assert {m.page_number for m in Search.indexed_content(storage, "నది", languages="te")} == {
            1,
            3,
        }

    def test_a_telugu_search_exports_as_telugu(self, storage: Storage, tmp_path):
        _index_file(storage, tmp_path, _BY_NAME["01_Telugu_Native_Letter.pdf"])
        matches = Search.indexed_content(storage, "తెలుగు", engine="like")

        Export.search_results(matches, "తెలుగు", tmp_path / "out.json", "json")
        Export.search_results(matches, "తెలుగు", tmp_path / "out.html", "html")

        payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert payload["languages"] == ["te"]
        assert payload["query_languages"] == ["te"]
        page = (tmp_path / "out.html").read_text(encoding="utf-8")
        assert '<html lang="te">' in page
        assert '<span lang="te">' in page
