import sqlite3
from datetime import UTC, datetime

import pytest
from vethuq_core.search import Search
from vethuq_core.search.engines import SearchQueryError
from vethuq_core.search.engines.fulltext import FullTextSearchEngine
from vethuq_core.search.engines.proximity import ProximitySearchEngine
from vethuq_core.settings import SearchSettings


class TestProximityEngine:
    @staticmethod
    def _seed(conn: sqlite3.Connection, text: str, path: str = "/docs/contract.pdf", page: int = 1):
        now = datetime.now(UTC).isoformat()
        source_id = conn.execute(
            "INSERT INTO sources (path, source_type, status, added_at) "
            "VALUES (?, 'folder', 'indexed', ?)",
            (path + ".src", now),
        ).lastrowid
        logical = conn.execute("INSERT INTO documents (created_at) VALUES (?)", (now,)).lastrowid
        document_id = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'pdf', 'indexed')",
            (source_id, logical, path),
        ).lastrowid
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
            "VALUES (?, ?, ?, 0.9)",
            (document_id, page, text),
        )
        conn.commit()

    @staticmethod
    def _near(storage, query, distance=None, **kwargs):
        return [
            m.matched
            for m in Search.indexed_content(
                storage, query, engine="proximity", distance=distance, **kwargs
            )
        ]

    def test_parse_terms_splits_words_phrases_and_prefixes(self):
        assert FullTextSearchEngine.parse_terms('payment "late fee" term*') == [
            '"payment"',
            '"late fee"',
            '"term" *',
        ]
        assert FullTextSearchEngine.parse_terms("NEAR( AND -x: ) ,") == ['"NEAR"', '"AND"', '"x"']
        assert FullTextSearchEngine.parse_terms("  ?! ") == []

    @pytest.mark.parametrize(
        ("text", "spans", "distance", "expected"),
        [
            # a b -> 0 words between
            ("aa bb", [[(0, 2)], [(3, 5)]], 0, [(0, 5)]),
            # aa w1 w2 bb -> 2 words between
            ("aa w1 w2 bb", [[(0, 2)], [(9, 11)]], 2, [(0, 11)]),
            ("aa w1 w2 bb", [[(0, 2)], [(9, 11)]], 1, []),
            # order doesn't matter
            ("bb w1 aa", [[(6, 8)], [(0, 2)]], 1, [(0, 8)]),
            # a term missing entirely
            ("aa w1 bb", [[(0, 2)], []], 5, []),
        ],
    )
    def test_find_clusters_counts_words_between_first_and_last_term(
        self, text, spans, distance, expected
    ):
        assert ProximitySearchEngine.find_clusters(text, spans, distance) == expected

    def test_find_clusters_counts_a_middle_term_as_a_word_between(self):
        # "aa w1 bb w2 w3 cc": bb, w1, w2, w3 lie between aa and cc -> 4, as FTS5's NEAR counts.
        text = "aa w1 bb w2 w3 cc"
        spans = [[(0, 2)], [(6, 8)], [(15, 17)]]

        assert ProximitySearchEngine.find_clusters(text, spans, 3) == []
        assert ProximitySearchEngine.find_clusters(text, spans, 4) == [(0, 17)]

    def test_find_clusters_finds_each_separate_passage_and_merges_overlaps(self):
        text = "aa bb x x x x x x x x x x x x aa bb"
        spans = [[(0, 2), (30, 32)], [(3, 5), (33, 35)]]

        assert ProximitySearchEngine.find_clusters(text, spans, 1) == [(0, 5), (30, 35)]
        # "bb aa bb": both bb...aa and aa...bb qualify and overlap -> one passage
        assert ProximitySearchEngine.find_clusters("bb aa bb", [[(3, 5)], [(0, 2), (6, 8)]], 0) == [
            (0, 8)
        ]

    def test_find_clusters_ignores_repeats_of_a_single_term(self):
        text = "aa aa aa x x x x x x x x x x x x bb"
        spans = [[(0, 2), (3, 5), (6, 8)], [(33, 35)]]

        # only the aa nearest bb can form a passage, and it is out of range
        assert ProximitySearchEngine.find_clusters(text, spans, 3) == []

    def test_proximity_engine_matches_terms_close_together_in_any_order(self, conn, storage):
        self._seed(
            conn, "The payment is due within thirty days, subject to the termination clause."
        )

        assert self._near(storage, "payment termination", 10) == [
            "payment is due within thirty days, subject to the termination"
        ]
        assert self._near(storage, "termination payment", 10) != []
        assert self._near(storage, "payment termination", 7) == []
        assert self._near(storage, "payment termination", 8) != []  # 8 words lie between them

    def test_proximity_engine_default_distance_is_ten_words(self, conn, storage):
        self._seed(conn, "payment " + "w " * 10 + "termination", path="/docs/ten.pdf")
        self._seed(conn, "payment " + "w " * 11 + "termination", path="/docs/eleven.pdf")

        matches = Search.indexed_content(storage, "payment termination", engine="proximity")

        assert [m.file_name for m in matches] == ["ten.pdf"]

    def test_proximity_engine_uses_the_stored_distance_and_presets(self, conn, storage):
        self._seed(conn, "payment " + "w " * 20 + "termination")

        assert self._near(storage, "payment termination") == []
        SearchSettings.set_proximity_distance(storage, "loose")  # 30 words
        assert self._near(storage, "payment termination") != []
        assert self._near(storage, "payment termination", "tight") == []

    def test_proximity_engine_terms_match_like_full_text(self, conn, storage):
        self._seed(conn, "Late Payments are charged; the TERMINATION of agreements follows")

        assert self._near(storage, "payment terminations agreement", 10) != []  # stemmed, any case
        assert self._near(storage, "charg* termin*", 10) != []  # prefixes
        assert self._near(storage, '"late payments" termination', 10) != []  # a phrase is one term
        assert self._near(storage, '"payments late" termination', 10) == []  # ...in order

    def test_proximity_engine_all_terms_must_be_within_the_distance(self, conn, storage):
        self._seed(conn, "aa w1 bb w2 w3 cc")

        assert self._near(storage, "aa bb cc", 3) == []
        assert self._near(storage, "aa bb cc", 4) == ["aa w1 bb w2 w3 cc"]

    def test_proximity_engine_returns_one_match_per_passage_with_context(self, conn, storage):
        self._seed(
            conn,
            "start payment then termination. " + "filler " * 30 + "termination and payment end",
        )

        matches = Search.indexed_content(
            storage, "payment termination", engine="proximity", distance=3, context_chars=6
        )

        assert [m.matched for m in matches] == [
            "payment then termination",
            "termination and payment",
        ]
        assert matches[0].before == "start " and matches[0].after == ". fill"
        assert matches[1].after == " end"
        assert all(m.score is not None for m in matches)

    def test_proximity_engine_ranks_pages_by_relevance_and_scores_passages(self, conn, storage):
        self._seed(conn, "payment then termination " * 6 + "filler " * 20, path="/docs/z_many.pdf")
        self._seed(conn, "payment then termination " + "filler " * 20, path="/docs/a_one.pdf")

        matches = Search.indexed_content(storage, "payment termination", engine="proximity")

        assert matches[0].file_name == "z_many.pdf"
        assert matches[0].score > matches[-1].score

    def test_proximity_engine_needs_two_terms(self, conn, storage):
        self._seed(conn, "payment then termination")

        with pytest.raises(SearchQueryError, match="at least two"):
            Search.indexed_content(storage, "payment", engine="proximity")
        with pytest.raises(SearchQueryError):
            Search.indexed_content(storage, "payment payment PAYMENT", engine="proximity")
        assert Search.indexed_content(storage, "  ?! ", engine="proximity") == []
        assert Search.indexed_content(storage, "", engine="proximity") == []

    def test_proximity_engine_treats_operators_and_punctuation_as_text(self, conn, storage):
        self._seed(conn, "salt AND pepper NEAR sugar")

        assert self._near(storage, "salt AND", 3) == ["salt AND"]
        for query in ('salt "unbalanced', "salt NEAR(", "salt -pepper:", "salt *", "() salt"):
            try:
                Search.indexed_content(storage, query, engine="proximity", distance=5)
            except SearchQueryError:
                pass  # too few terms is fine; an FTS5 syntax error is not

    def test_proximity_engine_rejects_case_sensitivity_threshold_and_bad_distances(self, storage):
        with pytest.raises(ValueError, match="case-insensitive"):
            Search.indexed_content(storage, "a b", engine="proximity", case_sensitive=True)
        with pytest.raises(ValueError, match="only fuzzy"):
            Search.indexed_content(storage, "a b", engine="proximity", threshold=0.8)
        for bad in (0, -1, 101, "nope"):
            with pytest.raises(ValueError):
                Search.indexed_content(storage, "aa bb", engine="proximity", distance=bad)

    @pytest.mark.parametrize("engine", ["like", "exact", "full-text", "fuzzy"])
    def test_other_engines_reject_a_distance(self, storage, engine):
        with pytest.raises(ValueError, match="only proximity"):
            Search.indexed_content(storage, "museum", engine=engine, distance=5)

    def test_proximity_engine_finds_image_pages_and_skips_non_indexed(self, conn, storage):
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
            text = "Signed by John Smith on behalf of the company"
            if kind == "image":
                conn.execute(
                    "INSERT INTO image_pages (document_id, ocr_text, confidence) "
                    "VALUES (?, ?, 0.9)",
                    (doc, text),
                )
            else:
                conn.execute(
                    "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                    "VALUES (?, 1, ?, 0.9)",
                    (doc, text),
                )
        conn.commit()

        matches = Search.indexed_content(storage, "signed company", engine="proximity", distance=7)

        assert [(m.file_name, m.page_number, m.matched) for m in matches] == [
            ("a.png", None, "Signed by John Smith on behalf of the company")
        ]

    def test_proximity_engine_duplicate_is_its_own_result(self, conn, storage):
        self._seed(conn, "payment then termination", path="/docs/original.pdf")
        original = conn.execute("SELECT document_id, source_id FROM document_index").fetchone()
        conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, '/docs/copy.pdf', 'pdf', 'indexed')",
            (original["source_id"], original["document_id"]),
        )
        conn.commit()

        matches = Search.indexed_content(storage, "payment termination", engine="proximity")

        assert {m.file_name: m.duplicate_of_path for m in matches} == {
            "original.pdf": None,
            "copy.pdf": "/docs/original.pdf",
        }

    def test_proximity_passages_agree_with_fts5_near_page_selection(self, conn, storage):
        """The Python passage check must accept exactly the pages FTS5's NEAR selected."""
        texts = [
            "aa bb",
            "aa w1 bb",
            "aa w1 w2 bb",
            "bb w1 w2 w3 aa",
            "aa w1 bb w2 w3 cc",
            "cc aa w1 w2 w3 w4 bb",
            "aa aa aa w1 w2 w3 w4 w5 bb",
            "a-b aa e_f bb",
            "aa\\nbb",
            "aa, w1; w2. bb",
        ]
        for i, text in enumerate(texts):
            self._seed(conn, text.replace("\\n", "\n"), path=f"/docs/{i}.pdf")

        for query in ("aa bb", "aa bb cc"):
            for distance in (1, 2, 3, 4, 5):
                found = {
                    m.file_name
                    for m in Search.indexed_content(
                        storage, query, engine="proximity", distance=distance
                    )
                }
                selected = {
                    row["file_path"].rsplit("/", 1)[1]
                    for row in storage.search_proximity_pdf_pages(
                        "NEAR("
                        + " ".join(FullTextSearchEngine.parse_terms(query))
                        + f", {distance})"
                    )
                }
                assert found == selected, (query, distance)
