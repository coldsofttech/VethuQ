import sqlite3

import pytest
from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.storage import Storage


class TestLexicalEngine:
    def test_finds_substring_mid_word_case_insensitively(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/a.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "A large MUSEUM")

        matches = Search.indexed_content(storage, "arge", engine="lexical")
        assert [m.matched for m in matches] == ["arge"]
        assert matches[0].engine == "lexical"
        assert matches[0].score is not None
        assert len(Search.indexed_content(storage, "museum", engine="lexical")) == 1

    def test_case_sensitive(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/a.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "Museum museum")

        matches = Search.indexed_content(storage, "Museum", engine="lexical", case_sensitive=True)
        assert len(matches) == 1

    def test_quotes_are_literal_not_fts_syntax(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/a.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, 'say "hello" AND NEAR')

        assert len(Search.indexed_content(storage, '"hello"', engine="lexical")) == 1
        assert len(Search.indexed_content(storage, "AND NEAR", engine="lexical")) == 1

    def test_ranks_denser_page_first(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        sparse = SearchData.add_document(conn, source_id, "/docs/a.pdf")
        dense = SearchData.add_document(conn, source_id, "/docs/b.pdf")
        SearchData.add_pdf_page(conn, sparse, 1, "invoice " + "filler " * 30)
        SearchData.add_pdf_page(conn, dense, 1, "invoice invoice invoice")

        matches = Search.indexed_content(storage, "invoice", engine="lexical")
        assert matches[0].file_path == "/docs/b.pdf"

    def test_query_under_three_characters_is_rejected(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        with pytest.raises(ValueError, match="at least 3"):
            Search.indexed_content(storage, "ab", engine="lexical")


class TestFts5Candidates:
    def test_trigram_match_quotes_and_enforces_minimum(self):
        assert SearchEngineHelpers.trigram_match("ab") is None
        assert SearchEngineHelpers.trigram_match('a"b') == '"a""b"'

    def test_like_fallback_for_short_queries(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/a.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "go to the mu")

        assert len(Search.indexed_content(storage, "mu", engine="like")) == 1

    def test_index_follows_update_and_delete(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/a.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "alpha text")

        conn.execute(
            "UPDATE pdf_pages SET ocr_text = 'bravo text' WHERE document_id = ?", (document_id,)
        )
        assert Search.indexed_content(storage, "alpha", engine="lexical") == []
        assert len(Search.indexed_content(storage, "bravo", engine="lexical")) == 1

        conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_id,))
        assert Search.indexed_content(storage, "bravo", engine="lexical") == []
