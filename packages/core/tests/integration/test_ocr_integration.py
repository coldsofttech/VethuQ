"""PDFs and images (PNG, JPG) read for real, English and Telugu, per each folder's `expected.json`.

It says what every file must come out as: its status, page count and, per page, where the text
came from (`native`, `ocr` or `mixed`) and phrases it must contain; Telugu entries also give
`searches` that must or must not find the file. Page text is checked through the public search
(`like`), which reports the page and how it was read.

    uv run pytest -m "integration and type_pdf and lang_en" packages/core/tests/integration
    (type_pdf, type_png or type_jpg; lang_en or lang_te)
    VETHUQ_REAL_OCR=1 VETHUQ_TELUGU_LICENCE=... uv run pytest -m "integration and lang_te" ...
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration import support as expected

TYPES = ("pdf", "png", "jpg")
DATA = {(lang, kind): expected.load(lang, kind) for lang in ("en", "te") for kind in TYPES}

pytestmark = pytest.mark.integration


def _cases(language: str, only=lambda entry: True):
    """Every entry of `language`, across the file types, marked `type_<kind>`."""
    return [
        pytest.param(
            kind,
            entry,
            id=f"{kind}-{entry['file'].split('_')[0]}",
            marks=[getattr(pytest.mark, f"type_{kind}"), *expected.case(entry).marks],
        )
        for kind in TYPES
        for entry in DATA[(language, kind)]["files"]
        if only(entry)
    ]


def _langs(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _index(client, tmp_path: Path, language: str, kind: str, entry: dict):
    """Index one fixture file; return its detailed file entry."""
    folder = tmp_path / "docs"
    folder.mkdir(exist_ok=True)
    (folder / entry["file"]).write_bytes(
        (expected.FIXTURES / language / kind / entry["file"]).read_bytes()
    )
    source = client.sources.create(folder, languages=_langs(entry.get("languages", language)))
    client.index.run(source.id)
    [file] = client.sources.list_files(source.id, detailed=True)
    return source, file


def _page_matches(client, language: str, file_name: str, number: int, source: str, phrase: str):
    """The matches on page `number` for `phrase`: the whole phrase for native text, each word for
    OCR (which is matched by most of its words)."""
    parts = [phrase] if source == "native" else expected.words(phrase)
    hits = []
    for part in parts:
        result = client.search.run(part, engine="like", languages=language, limit=1000)
        hits.append(
            [m for m in result.matches if m.file_name == file_name and m.page_number == number]
        )
    return parts, hits


def _check(client, tmp_path, language: str, kind: str, entry: dict):
    _, file = _index(client, tmp_path, language, kind, entry)
    index = file.index
    assert index.status.value == entry["status"], index.error
    if entry["status"] != "indexed":
        assert index.error
        return
    assert index.pages == entry["page_count"]
    floors = [w["min_confidence"] for w in entry["pages"].values() if "min_confidence" in w]
    if floors:  # the average of the pages is at least the lowest floor
        assert index.confidence >= min(floors)
    for number, want in entry["pages"].items():
        for phrase in want["contains"]:
            parts, hits = _page_matches(
                client, language, file.name, int(number), want["source"], phrase
            )
            share = 1.0 if want["source"] == "native" else expected.OCR_WORD_SHARE
            assert sum(bool(h) for h in hits) / len(parts) >= share, f"page {number}: {phrase!r}"
            assert {m.source for h in hits for m in h} <= {want["source"]}, f"page {number}"


class TestFixtures:
    @pytest.mark.parametrize(("language", "kind"), list(DATA))
    def test_every_fixture_has_an_expected_entry(self, language, kind):
        folder = expected.FIXTURES / language / kind
        data = DATA[(language, kind)]
        assert {p.name for p in folder.iterdir() if p.name != "expected.json"} == {
            e["file"] for e in data["files"]
        }
        assert (data["language"], data["file_type"]) == (language, kind)


@pytest.mark.lang_en
class TestEnglish:
    @pytest.mark.parametrize(("kind", "entry"), _cases("en"))
    def test_the_file_is_indexed_as_expected(self, kind, entry, client, tmp_path):
        _check(client, tmp_path, "en", kind, entry)


@pytest.mark.lang_te
class TestTelugu:
    @pytest.mark.parametrize(("kind", "entry"), _cases("te"))
    def test_the_file_is_indexed_as_expected(self, kind, entry, client, telugu, tmp_path):
        _check(client, tmp_path, "te", kind, entry)

    @pytest.mark.parametrize(("kind", "entry"), _cases("te", lambda e: bool(e.get("searches"))))
    def test_the_searches_find_what_they_should(self, kind, entry, client, telugu, tmp_path):
        _index(client, tmp_path, "te", kind, entry)
        for search in entry["searches"]:
            result = client.search.run(
                search["query"],
                engine=search.get("engine", "like"),
                languages=search.get("lang"),
            )
            assert bool(result.matches) is search.get("found", True), search
