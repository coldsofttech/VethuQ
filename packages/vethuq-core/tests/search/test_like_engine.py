import sqlite3

from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.storage import Storage


class TestLikeEngine:
    def test_search_is_case_insensitive(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/letter.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "URGENT NOTICE")

        matches = Search.indexed_content(storage, "urgent")

        assert len(matches) == 1

    def test_search_occurrences_do_not_overlap(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/a.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "aaaa")

        assert len(Search.indexed_content(storage, "aa")) == 2

    def test_search_matches_substring_inside_a_word(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        # The FTS5 index backing this search is trigram-tokenized specifically so
        # a query landing mid-word (not just on a whole-word/token boundary)
        # still matches, same as the plain substring scan this replaced.
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/invoice.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "a very large invoice")

        matches = Search.indexed_content(storage, "arge")

        assert len(matches) == 1
        assert matches[0].matched == "arge"

    def test_search_escapes_like_wildcard_characters(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/report.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "50% off, item_code: A1")

        # A literal "%"/"_" in the query must not act as a SQL LIKE wildcard.
        assert len(Search.indexed_content(storage, "50%")) == 1
        assert Search.indexed_content(storage, "50X") == []
        assert len(Search.indexed_content(storage, "item_code")) == 1
        assert Search.indexed_content(storage, "itemXcode") == []
