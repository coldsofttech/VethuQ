from datetime import UTC, datetime

import pytest
from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.search.engines.fuzzy import FuzzySearchEngine
from vethuq_core.settings import SearchSettings


class TestEditDistance:
    @pytest.mark.parametrize(
        ("a", "b", "distance"),
        [
            ("museum", "museum", 0),
            ("museum", "museums", 1),
            ("museum", "muzeum", 1),
            ("museum", "musem", 1),
            ("museum", "musuem", 1),  # a swap of neighbours is one edit
            ("museum", "museurn", 2),  # rn for m
            ("museum", "mustard", 3),  # over the limit of 2
        ],
    )
    def test_edit_distance(self, a, b, distance):
        assert FuzzySearchEngine.edit_distance(a, b, 2) == min(distance, 3)


class TestSimilarity:
    def test_similarity_is_one_minus_distance_over_longer_word(self):
        assert FuzzySearchEngine.similarity("museum", "museum", 0.8) == 1.0
        assert FuzzySearchEngine.similarity("museum", "museums", 0.8) == pytest.approx(1 - 1 / 7)
        assert FuzzySearchEngine.similarity("museum", "muzeum", 0.8) == pytest.approx(1 - 1 / 6)
        assert (
            FuzzySearchEngine.similarity("museum", "museurn", 0.8) is None
        )  # 0.71 is under balanced
        assert FuzzySearchEngine.similarity("museum", "museurn", 0.65) == pytest.approx(1 - 2 / 7)
        assert (
            FuzzySearchEngine.similarity("museum", "mustard", 0.1) is None
        )  # more than two edits, however loose

    def test_similarity_accepts_the_boundary_exactly(self):
        # One edit on a 5-letter word is exactly 0.8 (a hair off in floating point)...
        assert FuzzySearchEngine.similarity("bank", "banks", 0.8) == pytest.approx(0.8)
        assert FuzzySearchEngine.similarity("smith", "smyth", 0.8) == pytest.approx(0.8)
        # ...but on a 4-letter word it is 0.75, which needs the loose preset.
        assert FuzzySearchEngine.similarity("cats", "cast", 0.8) is None
        assert FuzzySearchEngine.similarity("cats", "cast", 0.65) == pytest.approx(0.75)

    def test_short_words_and_numbers_must_match_exactly(self):
        assert FuzzySearchEngine.similarity("cat", "car", 0.1) is None
        assert FuzzySearchEngine.similarity("cat", "cat", 0.9) == 1.0
        assert FuzzySearchEngine.similarity("2024", "2025", 0.1) is None
        assert FuzzySearchEngine.similarity("inv2024", "inv2025", 0.1) is None


class TestFuzzyEngine:
    @staticmethod
    def _found(storage, query, **kwargs):
        return [m.matched for m in Search.indexed_content(storage, query, engine="fuzzy", **kwargs)]

    @pytest.mark.parametrize(
        ("query", "hit"),
        [
            ("Museum", True),
            ("museum", True),
            ("Museums", True),
            ("Musuem", True),
            ("Muzeum", True),
            ("Musem", True),
            ("Museurn", False),  # 2 edits: under balanced...
            ("mus", False),  # too short to be fuzzy, and not the word
            ("seu", False),
            ("Mustard", False),
        ],
    )
    def test_balanced(self, conn, storage, query, hit):
        SearchData.seed_page(conn, "Visit the Museum today")

        assert bool(self._found(storage, query)) is hit

    def test_loose_catches_ocr_misreads(self, conn, storage):
        SearchData.seed_page(conn, "Visit the Museurn today")

        assert self._found(storage, "Museum") == []
        assert self._found(storage, "Museum", threshold=0.65) == ["Museurn"]
        SearchSettings.set_fuzzy_threshold(storage, "loose")
        assert self._found(storage, "Museum") == ["Museurn"]

    def test_strict_only_allows_the_smallest_differences(self, conn, storage):
        SearchData.seed_page(conn, "the museums and a muzeum")

        assert self._found(storage, "museum", threshold=0.8) == ["museums", "muzeum"]
        assert self._found(storage, "museum", threshold=0.9) == []
        assert self._found(storage, "museum", threshold=1) == []

    def test_scores_and_orders_closest_page_first(self, conn, storage):
        SearchData.seed_page(conn, "a muzeum guide", path="/docs/a_close.pdf")
        SearchData.seed_page(conn, "the museum guide", path="/docs/z_same.pdf")

        matches = Search.indexed_content(storage, "museum", engine="fuzzy")

        assert [m.file_name for m in matches] == ["z_same.pdf", "a_close.pdf"]
        assert matches[0].score == 1.0
        assert matches[1].score == pytest.approx(1 - 1 / 6)

    def test_every_word_must_match(self, conn, storage):
        SearchData.seed_page(conn, "the annual finance report", path="/docs/a.pdf")
        SearchData.seed_page(conn, "the annual weather report", path="/docs/b.pdf")

        matches = Search.indexed_content(storage, "anual finnce", engine="fuzzy")

        assert {m.file_name for m in matches} == {"a.pdf"}
        assert sorted(m.matched for m in matches) == ["annual", "finance"]

    def test_finds_every_occurrence_with_context(self, conn, storage):
        SearchData.seed_page(conn, "museum here, muzeum there.\nMuseums everywhere")

        matches = Search.indexed_content(storage, "museum", engine="fuzzy", context_chars=5)

        assert [m.matched for m in matches] == ["museum", "muzeum", "Museums"]
        assert matches[1].before == "ere, " and matches[1].after == " ther"

    def test_never_fuzzes_numbers_or_identifiers(self, conn, storage):
        SearchData.seed_page(conn, "Invoice INV-2024-00187 total 1200")

        assert self._found(storage, "2024") == ["2024"]
        assert self._found(storage, "2025") == []
        assert self._found(storage, "00181") == []
        assert self._found(storage, "invoce 2024") == ["Invoice", "2024"]

    def test_case_sensitivity_makes_a_case_difference_an_edit(self, conn, storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        assert self._found(storage, "museum") == ["Museum"]
        assert self._found(storage, "Museum", case_sensitive=True) == ["Museum"]
        # Case-sensitive, `m` vs `M` is one edit: still close at balanced, not at strict.
        assert self._found(storage, "museum", case_sensitive=True) == ["Museum"]
        assert self._found(storage, "museum", case_sensitive=True, threshold=0.9) == []

    def test_ignores_empty_and_symbol_only_queries(self, conn, storage):
        SearchData.seed_page(conn, "Visit the Museum today")

        assert self._found(storage, "") == []
        assert self._found(storage, "  ?! ") == []

    def test_rejects_invalid_threshold(self, storage):
        with pytest.raises(ValueError):
            Search.indexed_content(storage, "museum", engine="fuzzy", threshold=0)
        with pytest.raises(ValueError):
            Search.indexed_content(storage, "museum", engine="fuzzy", threshold=1.5)

    def test_finds_images_and_skips_non_indexed(self, conn, storage):
        now = datetime.now(UTC).isoformat()
        source_id = conn.execute(
            "INSERT INTO sources (path, source_type, status, added_at) VALUES ('/d', 'folder', "
            "'indexed', ?)",
            (now,),
        ).lastrowid
        for name, kind, status in (("a.png", "image", "indexed"), ("b.pdf", "pdf", "pending")):
            logical = conn.execute(
                "INSERT INTO documents (created_at) VALUES (?)", (now,)
            ).lastrowid
            doc = conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_id, logical, f"/d/{name}", kind, status),
            ).lastrowid
            if kind == "image":
                conn.execute(
                    "INSERT INTO image_pages (document_id, ocr_text, confidence) "
                    "VALUES (?, 'Signed by John Smyth', 0.9)",
                    (doc,),
                )
            else:
                conn.execute(
                    "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                    "VALUES (?, 1, 'Signed by John Smyth', 0.9)",
                    (doc,),
                )
        conn.commit()

        matches = Search.indexed_content(storage, "smith", engine="fuzzy")

        assert [(m.file_name, m.matched, m.page_number) for m in matches] == [
            ("a.png", "Smyth", None)
        ]

    def test_duplicate_is_its_own_result(self, conn, storage):
        SearchData.seed_page(conn, "the muzeum guide", path="/docs/original.pdf")
        original = conn.execute("SELECT id, document_id, source_id FROM document_index").fetchone()
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, '/docs/copy.pdf', 'pdf', 'indexed')",
            (original["source_id"], original["document_id"]),
        )
        conn.commit()

        matches = Search.indexed_content(storage, "museum", engine="fuzzy")

        assert {m.file_name: m.duplicate_of_path for m in matches} == {
            "original.pdf": None,
            "copy.pdf": "/docs/original.pdf",
        }


class TestNarrowing:
    def test_expression_only_narrows_where_it_is_sound(self):
        # 6 letters, up to 1 edit at balanced: any match shares one of the 4 trigrams.
        assert (
            FuzzySearchEngine.narrowing_expression(["museum"], 0.8)
            == '("eum" OR "mus" OR "seu" OR "use")'
        )
        # 4-5 letters: one edit can spoil every trigram, so no narrowing.
        assert FuzzySearchEngine.narrowing_expression(["bank"], 0.8) is None
        # exact words (short, or with digits) must appear literally, if 3+ characters
        assert FuzzySearchEngine.narrowing_expression(["cat", "2024"], 0.8) == '"cat" AND "2024"'
        assert FuzzySearchEngine.narrowing_expression(["of"], 0.8) is None
        # looser thresholds allow more edits, and stop narrowing sooner
        assert FuzzySearchEngine.narrowing_expression(["museum"], 0.65) is None

    def test_never_changes_the_results(self, conn, storage, monkeypatch):
        for i, text in enumerate(
            [
                "the museum guide",
                "a muzeum visit",
                "Museums and museum-goers",
                "nothing relevant here at all",
                "annual finance report",
                "anual finnce raport",
                "museu m split word",
                "MUSEUM in capitals",
            ]
        ):
            SearchData.seed_page(conn, text, path=f"/docs/{i}.pdf")

        for query in ("museum", "annual finance", "report", "muzeum guide"):
            for threshold in (0.65, 0.8, 0.9):
                narrowed = Search.indexed_content(
                    storage, query, engine="fuzzy", threshold=threshold
                )
                with monkeypatch.context() as patch:
                    patch.setattr(
                        FuzzySearchEngine,
                        "narrowing_expression",
                        staticmethod(lambda words, limit: None),
                    )
                    everything = Search.indexed_content(
                        storage, query, engine="fuzzy", threshold=threshold
                    )
                assert narrowed == everything
