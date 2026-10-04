"""Text read in a queued language pass is searchable: OCR, the pass, the indexes and the engines."""

from unittest.mock import patch

import pytest
from test_language_flow import JUNK, TELUGU, FakeEngine
from vethuq_core.ocr import Ocr
from vethuq_core.search import Search
from vethuq_core.sources import Sources


@pytest.fixture
def telugu_scan(storage, conn, tmp_path):
    """A scan English cannot read, so Telugu reads it in a queued pass; returns the source."""
    engines = {"en": FakeEngine("en", JUNK), "te": FakeEngine("te", TELUGU)}
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "scan.png").write_bytes(b"png bytes")
    source = Sources.add(storage, folder)
    with patch(
        "vethuq_core.ocr.engines.Engines.get",
        side_effect=lambda s, language=None: engines[language or "en"],
    ):
        Ocr.run_phased(storage, lambda: [Sources.get(storage, source.id)])
    return source


def _files(storage, query, engine):
    return [m.file_name for m in Search.indexed_content(storage, query, engine=engine)]


@pytest.mark.parametrize("engine", ["like", "exact", "full-text", "fuzzy", "noise-fuzzy"])
def test_the_text_a_queued_pass_added_is_found_by_every_engine(storage, telugu_scan, engine):
    assert _files(storage, "పాఠం", engine) == ["scan.png"]


def test_the_combined_search_finds_it_too(storage, telugu_scan):
    assert [r.file_name for r in Search.indexed_pages(storage, "అమ్మ ఇల్లు")] == ["scan.png"]


def test_a_phrase_and_a_prefix_work_on_text_added_by_a_pass(storage, telugu_scan):
    assert _files(storage, '"అమ్మ ఇల్లు"', "full-text") == ["scan.png"]
    assert _files(storage, "తెలు*", "full-text") == ["scan.png"]


def test_the_text_the_first_language_made_up_is_not_searchable(storage, telugu_scan):
    assert _files(storage, "qzxv", "like") == []
    assert _files(storage, "qzxv", "full-text") == []


def test_the_derived_search_text_was_recorded_with_the_signs(conn, telugu_scan):
    row = conn.execute("SELECT noise_text, norm_text FROM image_pages").fetchone()

    assert "ాఠ" in row["noise_text"] and "ాఠ" in row["norm_text"]
