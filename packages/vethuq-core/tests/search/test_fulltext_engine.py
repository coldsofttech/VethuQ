import sqlite3

import pytest
from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.storage import Storage


class TestFullTextEngine:
    @pytest.mark.parametrize(
        ("query", "hit"),
        [
            ("museum", True),
            ("MUSEUM", True),
            ("Museums", True),  # stemmed
            ("mus", False),  # not a whole word...
            ("mus*", True),  # ...unless it's a prefix query
            ("seu", False),
            ("euma", False),
        ],
    )
    def test_matches_whole_words_stemmed(
        self, conn: sqlite3.Connection, storage: Storage, query: str, hit: bool
    ):
        SearchData.seed_page(conn, "Visit the Museum today")

        matches = Search.indexed_content(storage, query, engine="full-text")

        assert bool(matches) is hit
        assert all(m.matched.lower().startswith("museum") for m in matches)

    def test_highlights_the_matched_word_with_context(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "Two Museums stand near one museum.\nOpen daily.")

        matches = Search.indexed_content(storage, "museum", engine="full-text", context_chars=6)

        assert [(m.before, m.matched, m.after) for m in matches] == [
            ("Two ", "Museums", " stand"),
            ("r one ", "museum", ". Open"),
        ]
        assert not any("\x02" in m.before + m.matched + m.after for m in matches)

    def test_phrase_and_all_terms_required(self, conn: sqlite3.Connection, storage: Storage):
        SearchData.seed_page(conn, "amount due by Friday, total amount is high", path="/docs/a.pdf")
        SearchData.seed_page(conn, "the due amount is small", path="/docs/b.pdf")

        phrase = Search.indexed_content(storage, '"amount due"', engine="full-text")
        both = Search.indexed_content(storage, "due amount", engine="full-text")

        assert [m.file_name for m in phrase] == ["a.pdf"]
        assert {m.file_name for m in both} == {"a.pdf", "b.pdf"}
        assert Search.indexed_content(storage, "amount zebra", engine="full-text") == []

    def test_folds_accents(self, conn: sqlite3.Connection, storage: Storage):
        SearchData.seed_page(conn, "Un caf\u00e9 au lait")

        assert len(Search.indexed_content(storage, "cafe", engine="full-text")) == 1

    def test_ranks_best_page_first(self, conn: sqlite3.Connection, storage: Storage):
        SearchData.seed_page(conn, "budget " * 10 + "filler " * 40, path="/docs/z_many.pdf")
        SearchData.seed_page(conn, "one budget among " + "filler " * 40, path="/docs/a_few.pdf")

        matches = Search.indexed_content(storage, "budget", engine="full-text")

        assert matches[0].file_name == "z_many.pdf"
        assert matches[0].score is not None and matches[-1].score is not None
        assert matches[0].score > matches[-1].score

    def test_treats_operators_and_punctuation_as_text(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        SearchData.seed_page(conn, "salt AND pepper, not sugar: NEAR the sea - fresh")

        for query in ('"unbalanced', "AND", "NEAR(", "sugar:", "-fresh", "salt OR", "*", "()"):
            Search.indexed_content(storage, query, engine="full-text")  # must not raise

        assert len(Search.indexed_content(storage, "AND", engine="full-text")) == 1
        assert Search.indexed_content(storage, "*", engine="full-text") == []
        assert Search.indexed_content(storage, "   ", engine="full-text") == []

    def test_rejects_case_sensitive(self, storage: Storage):
        with pytest.raises(ValueError, match="case-insensitive"):
            Search.indexed_content(storage, "museum", engine="full-text", case_sensitive=True)

    def test_finds_image_pages_and_excludes_non_indexed(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        image_id = SearchData.add_document(conn, source_id, "/docs/scan.png", file_type="image")
        SearchData.add_image_page(conn, image_id, "Signed by John Doe")
        pending_id = SearchData.add_document(conn, source_id, "/docs/p.pdf", status="pending")
        SearchData.add_pdf_page(conn, pending_id, 1, "John Doe pending")

        matches = Search.indexed_content(storage, "john", engine="full-text")

        assert [m.file_name for m in matches] == ["scan.png"]
        assert matches[0].page_number is None

    def test_index_follows_page_updates_and_deletes(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        document_id = SearchData.seed_page(conn, "alpha beta")
        conn.execute(
            "UPDATE pdf_pages SET ocr_text = 'gamma delta' WHERE document_id = ?", (document_id,)
        )
        conn.commit()

        assert Search.indexed_content(storage, "alpha", engine="full-text") == []
        assert len(Search.indexed_content(storage, "gamma", engine="full-text")) == 1

        conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_id,))
        conn.commit()
        assert Search.indexed_content(storage, "gamma", engine="full-text") == []

    def test_returns_duplicate_as_its_own_result(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        original_id = SearchData.add_document(conn, source_id, "/docs/original.pdf")
        SearchData.add_pdf_page(conn, original_id, 1, "Total amount due")
        logical = conn.execute(
            "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
        ).fetchone()["document_id"]
        SearchData.add_document(conn, source_id, "/docs/copy.pdf", document_id=logical)

        matches = Search.indexed_content(storage, "amount", engine="full-text")

        assert {m.file_name: m.duplicate_of_path for m in matches} == {
            "original.pdf": None,
            "copy.pdf": "/docs/original.pdf",
        }
        assert all(m.total_pages == 1 for m in matches)
