import sqlite3
from datetime import UTC, datetime

import pytest
from vethuq_core.search import Search
from vethuq_core.search.engines import (
    FallbackSearchEngine,
    SearchEngines,
    SearchEngineUnavailable,
)
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


def _add_source(conn: sqlite3.Connection, path: str = "/docs") -> int:
    now = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        "INSERT INTO sources (path, source_type, status, added_at) "
        "VALUES (?, 'folder', 'indexed', ?)",
        (path, now),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_document(
    conn: sqlite3.Connection,
    source_id: int,
    file_path: str,
    file_type: str = "pdf",
    status: str = "indexed",
    document_id: int | None = None,
) -> int:
    """Insert a `document_index` row, creating a fresh logical `documents` row unless `document_id`
    (another row's logical document, to link this one as sharing its content) is given."""
    if document_id is None:
        document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
        ).lastrowid
    cursor = conn.execute(
        "INSERT INTO document_index "
        "(source_id, document_id, file_path, file_type, status) VALUES (?, ?, ?, ?, ?)",
        (source_id, document_id, file_path, file_type, status),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_pdf_page(conn: sqlite3.Connection, document_id: int, page_number: int, text: str) -> None:
    conn.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
        "VALUES (?, ?, ?, 0.95)",
        (document_id, page_number, text),
    )
    conn.commit()


def _add_image_page(conn: sqlite3.Connection, document_id: int, text: str) -> None:
    conn.execute(
        "INSERT INTO image_pages (document_id, ocr_text, confidence) VALUES (?, ?, 0.95)",
        (document_id, text),
    )
    conn.commit()


class TestSearch:
    def test_files_collapses_pages_into_one_result_per_file(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        report = _add_document(conn, source_id, "/docs/report.pdf")
        _add_pdf_page(conn, report, 1, "budget overview")
        _add_pdf_page(conn, report, 2, "final budget numbers")
        memo = _add_document(conn, source_id, "/docs/memo.pdf")
        _add_pdf_page(conn, memo, 1, "budget memo")

        files = Search.files(storage, "budget")

        assert [(f.file_name, f.is_duplicate) for f in files] == [
            ("memo.pdf", False),
            ("report.pdf", False),
        ]

    def test_files_empty_query_returns_empty_list(self, storage: Storage):
        assert Search.files(storage, "") == []

    def test_search_matches_pdf_page(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
        _add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")

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
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/scan.png", file_type="image")
        _add_image_page(conn, document_id, "Signed by John Doe on 2026-01-01")

        matches = Search.indexed_content(storage, "john doe")

        assert len(matches) == 1
        assert matches[0].file_name == "scan.png"
        assert matches[0].page_number is None
        assert matches[0].total_pages is None
        assert matches[0].matched == "John Doe"

    def test_search_excludes_removed_source(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
        _add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")
        conn.execute(
            "UPDATE sources SET is_active = 0, status = 'removed' WHERE id = ?", (source_id,)
        )
        conn.commit()

        matches = Search.indexed_content(storage, "amount due")

        assert matches == []

    def test_search_is_case_insensitive(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/letter.pdf")
        _add_pdf_page(conn, document_id, 1, "URGENT NOTICE")

        matches = Search.indexed_content(storage, "urgent")

        assert len(matches) == 1

    def test_search_returns_one_row_per_matching_page(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/report.pdf")
        _add_pdf_page(conn, document_id, 1, "budget overview")
        _add_pdf_page(conn, document_id, 2, "no match here")
        _add_pdf_page(conn, document_id, 3, "final budget numbers")

        matches = Search.indexed_content(storage, "budget")

        assert len(matches) == 2
        assert [m.file_id for m in matches] == [document_id, document_id]
        assert [m.page_number for m in matches] == [1, 3]
        assert [m.total_pages for m in matches] == [3, 3]

    def test_search_ignores_non_indexed_documents(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/pending.pdf", status="pending")
        _add_pdf_page(conn, document_id, 1, "confidential findings")

        matches = Search.indexed_content(storage, "confidential")

        assert matches == []

    def test_search_no_matches_returns_empty_list(self, conn: sqlite3.Connection, storage: Storage):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/notes.pdf")
        _add_pdf_page(conn, document_id, 1, "nothing relevant")

        assert Search.indexed_content(storage, "unrelated term") == []

    def test_search_empty_query_returns_empty_list(self, storage: Storage):
        assert Search.indexed_content(storage, "") == []

    def test_search_snippet_context_is_configurable(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/long.pdf")
        text = "x" * 100 + "TARGET" + "y" * 100
        _add_pdf_page(conn, document_id, 1, text)

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
        source_id = _add_source(conn)
        original_id = _add_document(conn, source_id, "/docs/original.pdf")
        _add_pdf_page(conn, original_id, 1, "Total amount due: $1,200.00 by Friday.")
        original_document_id = conn.execute(
            "SELECT document_id FROM document_index WHERE id = ?", (original_id,)
        ).fetchone()["document_id"]
        duplicate_id = _add_document(
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

    def test_search_matches_substring_inside_a_word(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        # The FTS5 index backing this search is trigram-tokenized specifically so
        # a query landing mid-word (not just on a whole-word/token boundary)
        # still matches, same as the plain substring scan this replaced.
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
        _add_pdf_page(conn, document_id, 1, "a very large invoice")

        matches = Search.indexed_content(storage, "arge")

        assert len(matches) == 1
        assert matches[0].matched == "arge"

    def test_search_escapes_like_wildcard_characters(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/report.pdf")
        _add_pdf_page(conn, document_id, 1, "50% off, item_code: A1")

        # A literal "%"/"_" in the query must not act as a SQL LIKE wildcard.
        assert len(Search.indexed_content(storage, "50%")) == 1
        assert Search.indexed_content(storage, "50X") == []
        assert len(Search.indexed_content(storage, "item_code")) == 1
        assert Search.indexed_content(storage, "itemXcode") == []

    def test_search_context_chars_argument_overrides_setting(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        source_id = _add_source(conn)
        document_id = _add_document(conn, source_id, "/docs/long.pdf")
        text = "x" * 100 + "TARGET" + "y" * 100
        _add_pdf_page(conn, document_id, 1, text)

        matches = Search.indexed_content(storage, "target", context_chars=5)

        assert matches[0].before == "x" * 5
        assert matches[0].after == "y" * 5


class TestSearchEngines:
    def test_registry_default_and_unknown(self, storage: Storage):
        assert SearchEngines.get(storage).name == "like"
        with pytest.raises(ValueError, match="Unknown search engine"):
            SearchEngines.get(storage, "nope")

    def test_fallback_engine_uses_fallback_when_primary_unavailable(self, storage: Storage):
        class Broken:
            name = "broken"

            def search(self, query, *, context_chars=None):
                raise SearchEngineUnavailable

        engine = FallbackSearchEngine(Broken(), SearchEngines.get(storage))
        assert engine.name == "broken->like"
        assert engine.search("") == []
