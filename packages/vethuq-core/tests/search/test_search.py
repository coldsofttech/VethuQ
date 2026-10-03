import sqlite3

from search_data import SearchData
from vethuq_core.search import Search
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class TestSearch:
    def test_files_collapses_pages_into_one_result_per_file(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        report = SearchData.add_document(conn, source_id, "/docs/report.pdf")
        SearchData.add_pdf_page(conn, report, 1, "budget overview")
        SearchData.add_pdf_page(conn, report, 2, "final budget numbers")
        memo = SearchData.add_document(conn, source_id, "/docs/memo.pdf")
        SearchData.add_pdf_page(conn, memo, 1, "budget memo")

        files = Search.files(storage, "budget")

        assert [(f.file_name, f.is_duplicate) for f in files] == [
            ("memo.pdf", False),
            ("report.pdf", False),
        ]

    def test_files_empty_query_returns_empty_list(self, storage: Storage):
        assert Search.files(storage, "") == []

    def test_search_matches_pdf_page(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/invoice.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")

        matches = Search.indexed_content(storage, "amount due")

        assert len(matches) == 1
        match = matches[0]
        assert match.file_id == document_id
        assert match.file_name == "invoice.pdf"
        assert match.page_number == 1
        assert match.total_pages == 1
        assert match.matched == "amount due"
        assert "Total " in match.before
        assert ": $1,200.00 by Friday." in match.after

    def test_search_matches_image_page(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/scan.png", file_type="image")
        SearchData.add_image_page(conn, document_id, "Signed by John Doe on 2026-01-01")

        matches = Search.indexed_content(storage, "john doe")

        assert len(matches) == 1
        assert matches[0].file_name == "scan.png"
        assert matches[0].page_number is None
        assert matches[0].total_pages is None
        assert matches[0].matched == "John Doe"

    def test_search_excludes_removed_source(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/invoice.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")
        conn.execute(
            "UPDATE sources SET is_active = 0, status = 'removed' WHERE id = ?", (source_id,)
        )
        conn.commit()

        matches = Search.indexed_content(storage, "amount due")

        assert matches == []

    def test_search_returns_one_row_per_matching_page(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/report.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "budget overview")
        SearchData.add_pdf_page(conn, document_id, 2, "no match here")
        SearchData.add_pdf_page(conn, document_id, 3, "final budget numbers")

        matches = Search.indexed_content(storage, "budget")

        assert len(matches) == 2
        assert [m.file_id for m in matches] == [document_id, document_id]
        assert [m.page_number for m in matches] == [1, 3]
        assert [m.total_pages for m in matches] == [3, 3]

    def test_search_returns_every_occurrence_within_a_page(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/report.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "Budget up, budget down.\nBUDGET flat")
        SearchData.add_pdf_page(conn, document_id, 2, "one budget")

        matches = Search.indexed_content(storage, "budget", context_chars=4)

        assert [(m.page_number, m.matched) for m in matches] == [
            (1, "Budget"),
            (1, "budget"),
            (1, "BUDGET"),
            (2, "budget"),
        ]
        assert matches[0].before == "" and matches[0].after == " up,"
        assert matches[1].before == "up, " and matches[1].after == " dow"
        assert matches[2].before == "wn. " and matches[2].after == " fla"

    def test_search_ignores_non_indexed_documents(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(
            conn, source_id, "/docs/pending.pdf", status="pending"
        )
        SearchData.add_pdf_page(conn, document_id, 1, "confidential findings")

        matches = Search.indexed_content(storage, "confidential")

        assert matches == []

    def test_search_no_matches_returns_empty_list(self, conn: sqlite3.Connection, storage: Storage):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/notes.pdf")
        SearchData.add_pdf_page(conn, document_id, 1, "nothing relevant")

        assert Search.indexed_content(storage, "unrelated term") == []

    def test_search_empty_query_returns_empty_list(self, storage: Storage):
        assert Search.indexed_content(storage, "") == []

    def test_search_snippet_context_is_configurable(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/long.pdf")
        text = "x" * 100 + "TARGET" + "y" * 100
        SearchData.add_pdf_page(conn, document_id, 1, text)

        SearchSettings.set_snippet_context_chars(storage, 10)
        matches = Search.indexed_content(storage, "target")

        assert len(matches) == 1
        assert matches[0].before == "x" * 10
        assert matches[0].after == "y" * 10
        assert matches[0].truncated_before is True
        assert matches[0].truncated_after is True

    def test_search_returns_duplicate_as_its_own_flagged_result(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        original_id = SearchData.add_document(conn, source_id, "/docs/original.pdf")
        SearchData.add_pdf_page(conn, original_id, 1, "Total amount due: $1,200.00 by Friday.")
        original_document_id = conn.execute(
            "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
        ).fetchone()["document_id"]
        duplicate_id = SearchData.add_document(
            conn, source_id, "/docs/copy.pdf", document_id=original_document_id
        )

        matches = Search.indexed_content(storage, "amount due")

        assert len(matches) == 2
        by_file_id = {m.file_id: m for m in matches}
        assert by_file_id[original_id].duplicate_of_path is None
        assert by_file_id[duplicate_id].file_name == "copy.pdf"
        assert by_file_id[duplicate_id].duplicate_of_path == "/docs/original.pdf"
        assert by_file_id[duplicate_id].matched == "amount due"
        assert by_file_id[duplicate_id].total_pages == 1

    def test_search_context_chars_argument_overrides_setting(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = SearchData.add_source(conn)
        document_id = SearchData.add_document(conn, source_id, "/docs/long.pdf")
        text = "x" * 100 + "TARGET" + "y" * 100
        SearchData.add_pdf_page(conn, document_id, 1, text)

        matches = Search.indexed_content(storage, "target", context_chars=5)

        assert matches[0].before == "x" * 5
        assert matches[0].after == "y" * 5
