"""Telugu JPG and JPEG images read with the real PaddleOCR models, per `expected.json`.

`fixtures/te/jpg/expected.json` says what each image must come out as: the languages its source
is read in, its status and, for its one page, the languages it was read in, the OCR confidence it
must reach and phrases it must contain; and `searches` that must or must not find it. Some files
are `.jpg` and some `.jpeg` (one format under two extensions, which must be read alike). The images
are made by `scripts/dev/generate_telugu_fixtures.py jpg` and the expectations by
`scripts/dev/generate_integration_expected.py --lang te --dir <this folder>`.

Every image is read with the real PaddleOCR models, English and Telugu, so these cases run only
when `VETHUQ_REAL_OCR=1` (set by `.github/workflows/integration.yml`, which downloads the models
first). Locally:

    uv run vethuq ocr models download --lang en --lang te
    VETHUQ_REAL_OCR=1 uv run pytest -m "integration and lang_te and type_jpg" \\
        packages/vethuq-core/tests/integration
"""

import json
import sqlite3
from pathlib import Path

import expected_support as expected
import pytest
from vethuq_core.ocr import Ocr
from vethuq_core.search import Export, Search
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Sources
from vethuq_core.stats import Confidence, Processing
from vethuq_core.storage import Storage

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "te" / "jpg"
EXPECTED = expected.load(FIXTURES_DIR)
LANGUAGE = EXPECTED["language"]

pytestmark = [pytest.mark.integration, pytest.mark.lang_te, pytest.mark.type_jpg]

_ENTRIES = EXPECTED["files"]
_BY_NAME = {entry["file"]: entry for entry in _ENTRIES}
_SEARCHED = [e for e in _ENTRIES if e["status"] == "indexed" and e.get("searches")]


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
    path = folder / entry["file"]
    path.write_bytes((FIXTURES_DIR / entry["file"]).read_bytes())
    source = Sources.add(storage, path, languages=entry.get("languages", LANGUAGE))
    Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
    return path


class TestFixtures:
    def test_every_fixture_has_an_expected_entry(self):
        on_disk = {path.name for path in FIXTURES_DIR.iterdir() if path.suffix != ".json"}

        assert on_disk == {entry["file"] for entry in _ENTRIES}

    def test_the_expected_file_names_its_language_and_type(self):
        assert EXPECTED["language"] == "te"
        assert EXPECTED["file_type"] == "jpg"

    def test_both_extensions_are_present(self):
        suffixes = {Path(entry["file"]).suffix for entry in _ENTRIES}

        assert suffixes == {".jpg", ".jpeg"}

    def test_the_variants_are_what_their_names_say(self):
        from PIL import Image

        def open_(name):
            return Image.open(FIXTURES_DIR / name)

        with open_("16_Telugu_Grayscale.jpg") as image:
            assert image.mode == "L"
        with open_("17_Telugu_Progressive.jpeg") as image:
            assert image.info.get("progressive") or image.info.get("progression")
        with open_("21_Telugu_EXIF_Rotated.jpg") as image:
            assert image.getexif().get(0x0112) == 6
            assert image.size[0] < image.size[1]  # stored on its side
        with open_("20_Telugu_Wide_Strip.jpeg") as image:
            assert image.size[0] / image.size[1] > 40
        # Quality 8 against 90: the same page, far fewer bytes.
        heavy = (FIXTURES_DIR / "10_Telugu_Heavy_Compression.jpeg").stat().st_size
        clean = (FIXTURES_DIR / "01_Telugu_Clean.jpg").stat().st_size
        assert heavy < clean / 2

    def test_a_jpeg_is_a_jpeg_whatever_its_extension(self):
        for name in ("01_Telugu_Clean.jpg", "02_Telugu_Letter.jpeg"):
            assert (FIXTURES_DIR / name).read_bytes()[:3] == b"\xff\xd8\xff"

    def test_the_duplicate_is_byte_identical_to_the_original(self):
        original = (FIXTURES_DIR / "01_Telugu_Clean.jpg").read_bytes()

        assert (FIXTURES_DIR / "24_Telugu_Duplicate_Of_01.jpeg").read_bytes() == original


class TestTeluguJpgIntegration:
    @pytest.mark.parametrize("entry", [expected.case(e) for e in _ENTRIES])
    def test_the_image_is_indexed_as_expected(
        self, entry, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        path = _index_file(storage, tmp_path, entry)

        doc = conn.execute(
            "SELECT * FROM document_index WHERE file_path = ?", (str(path.resolve()),)
        ).fetchone()
        assert doc["status"] == entry["status"], doc["error_message"]
        if entry["status"] != "indexed":
            assert doc["error_message"]
            assert conn.execute("SELECT COUNT(*) FROM image_pages").fetchone()[0] == 0
            return

        assert doc["file_type"] == "image"
        assert Path(doc["file_path"]).suffix in {".jpg", ".jpeg"}
        assert Path(doc["file_path"]).name == entry["file"]
        assert doc["file_size_bytes"] == (FIXTURES_DIR / entry["file"]).stat().st_size
        pages = conn.execute(
            "SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)
        ).fetchall()
        assert len(pages) == entry["page_count"]
        want = entry["pages"]["1"]
        page = pages[0]
        assert set(want["read_in"]) <= _read_in(page), _read_in(page)
        if "min_confidence" in want:
            assert page["confidence"] >= want["min_confidence"]
        for phrase in want["contains"]:
            assert expected.contains(page["ocr_text"], phrase, want["source"]), phrase

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


class TestAcrossFiles:
    @expected.needs_models
    def test_a_duplicate_shares_the_originals_pages_and_language(self, storage: Storage, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        for name in ("01_Telugu_Clean.jpg", "24_Telugu_Duplicate_Of_01.jpeg"):
            (folder / name).write_bytes((FIXTURES_DIR / name).read_bytes())
        source = Sources.add(storage, folder, languages="te")

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        found = Search.indexed_content(storage, "తెలుగు", engine="like", languages="te")
        assert {m.file_name for m in found} == {
            "01_Telugu_Clean.jpg",
            "24_Telugu_Duplicate_Of_01.jpeg",
        }
        assert Search.indexed_content(storage, "తెలుగు", engine="like", languages="en") == []

    @expected.needs_models
    def test_jpg_and_jpeg_are_reported_under_one_extension(self, storage: Storage, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        for name in ("01_Telugu_Clean.jpg", "02_Telugu_Letter.jpeg"):
            (folder / name).write_bytes((FIXTURES_DIR / name).read_bytes())
        source = Sources.add(storage, folder, languages="te")

        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])

        assert {m.extension for m in Processing.get_metrics(storage)} == {"jpg"}
        assert {m.language for m in Processing.get_metrics(storage)} == {"te"}

    @expected.needs_models
    def test_statistics_are_kept_under_telugu(self, storage: Storage, tmp_path):
        _index_file(storage, tmp_path, _BY_NAME["01_Telugu_Clean.jpg"])

        metrics = Confidence.get_metrics(storage)

        assert {m.language for m in metrics} == {"te"}
        assert metrics[0].page_count == 1
        assert (
            metrics[0].avg_confidence
            >= _BY_NAME["01_Telugu_Clean.jpg"]["pages"]["1"]["min_confidence"]
        )

    @expected.needs_models
    def test_a_telugu_search_exports_as_telugu(self, storage: Storage, tmp_path):
        _index_file(storage, tmp_path, _BY_NAME["01_Telugu_Clean.jpg"])
        matches = Search.indexed_content(storage, "తెలుగు", engine="like")

        Export.search_results(matches, "తెలుగు", tmp_path / "out.json", "json")
        Export.search_results(matches, "తెలుగు", tmp_path / "out.html", "html")

        payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert payload["languages"] == ["te"]
        assert payload["query_languages"] == ["te"]
        page = (tmp_path / "out.html").read_text(encoding="utf-8")
        assert '<html lang="te">' in page
        assert '<span lang="te">' in page
