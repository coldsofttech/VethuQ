import json
from pathlib import Path

import pytest
from search_data import SearchData
from vethuq_core.search import Export, Search
from vethuq_core.storage import Storage

ENGINES = ["like", "lexical", "exact", "full-text", "fuzzy"]


class TestUnicodeQueries:
    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize(
        ("text", "query"),
        [
            ("Visit the café on Rue Saint-Honoré", "café"),
            ("Straße nach Düsseldorf", "Düsseldorf"),
            ("Привет мир, добро пожаловать", "мир"),
            ("東京 美術館 を訪れる", "美術館"),
            ("مرحبا بالعالم الجميل", "بالعالم"),
            ("Ceny w złotych: żółć", "żółć"),
        ],
    )
    def test_matches_and_displays_non_ascii_text(
        self, conn, storage: Storage, engine: str, text: str, query: str
    ):
        SearchData.seed_page(conn, text)

        matches = Search.indexed_content(storage, query, engine=engine)

        assert matches, f"{engine} found nothing for {query!r}"
        assert matches[0].matched == query
        assert query in matches[0].before + matches[0].matched + matches[0].after

    @pytest.mark.parametrize("engine", ["like", "full-text", "fuzzy"])
    def test_non_ascii_case_is_folded(self, conn, storage: Storage, engine: str):
        SearchData.seed_page(conn, "ÉCOLE Normale Supérieure, ПРИВЕТ")

        assert [m.matched for m in Search.indexed_content(storage, "école", engine=engine)] == [
            "ÉCOLE"
        ]
        assert [m.matched for m in Search.indexed_content(storage, "привет", engine=engine)] == [
            "ПРИВЕТ"
        ]

    def test_full_text_folds_diacritics_in_either_direction(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the café and the resume")

        assert Search.indexed_content(storage, "cafe", engine="full-text")
        assert Search.indexed_content(storage, "résumé", engine="full-text")

    def test_like_and_lexical_match_contiguous_cjk_text(self, conn, storage: Storage):
        SearchData.seed_page(conn, "東京都の美術館を訪れる")

        for engine in ("like", "lexical"):
            assert [
                m.matched for m in Search.indexed_content(storage, "美術館", engine=engine)
            ] == ["美術館"]

    def test_proximity_matches_non_ascii_words(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Le café est très près de la école")

        matches = Search.indexed_content(storage, "café école", engine="proximity", distance=8)

        assert matches
        assert "café" in matches[0].matched and "école" in matches[0].matched

    def test_preserves_the_original_text_in_results(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the Café Noël today")

        (match,) = Search.indexed_content(storage, "cafe", engine="full-text")

        assert match.matched == "Café"
        assert match.after.startswith(" Noël")

    def test_exact_is_case_sensitive_for_non_ascii(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Ça va très bien")

        assert Search.indexed_content(storage, "ça", engine="exact") == []
        assert [m.matched for m in Search.indexed_content(storage, "Ça", engine="exact")] == ["Ça"]

    def test_matches_a_unicode_file_name(self, conn, storage: Storage):
        SearchData.seed_page(conn, "contenu", path="/docs/été-日本語.pdf")

        (match,) = Search.indexed_content(storage, "contenu")

        assert match.file_name == "été-日本語.pdf"
        assert match.file_path == "/docs/été-日本語.pdf"


class TestUnicodeExport:
    def _matches(self, conn, storage: Storage):
        SearchData.seed_page(conn, "Visit the café 東京 today", path="/docs/été.pdf")
        return Search.indexed_content(storage, "café")

    def test_html_export_keeps_non_ascii_characters(self, conn, storage: Storage, tmp_path: Path):
        output = tmp_path / "out.html"

        Export.search_results(self._matches(conn, storage), "café", output, "html")

        text = output.read_text(encoding="utf-8")
        assert "<mark>café</mark> 東京" in text
        assert "été.pdf" in text
        assert 'charset="utf-8"' in text.lower() or "charset=utf-8" in text.lower()

    def test_json_export_keeps_non_ascii_characters(self, conn, storage: Storage, tmp_path: Path):
        output = tmp_path / "out.json"

        Export.search_results(self._matches(conn, storage), "café", output, "json")

        raw = output.read_text(encoding="utf-8")
        assert "café 東京" in raw
        payload = json.loads(raw)
        assert payload["query"] == "café"
        assert payload["matches"][0]["file_name"] == "été.pdf"
