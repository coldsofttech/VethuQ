import sqlite3
from datetime import UTC, datetime

import pytest
from vethuq_core.db import connect
from vethuq_core.search import search_indexed_content
from vethuq_core.settings import set_search_snippet_context_chars


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "vethuq.db")
    yield connection
    connection.close()


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
    duplicate_of_id: int | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO document_index "
        "(source_id, file_path, file_type, status, duplicate_of_id) VALUES (?, ?, ?, ?, ?)",
        (source_id, file_path, file_type, status, duplicate_of_id),
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


def test_search_matches_pdf_page(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
    _add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")

    matches = search_indexed_content(conn, "amount due")

    assert len(matches) == 1
    match = matches[0]
    assert match.file_id == document_id
    assert match.file_name == "invoice.pdf"
    assert match.page_number == 1
    assert match.total_pages == 1
    assert match.matched == "amount due"
    assert "Total " in match.before
    assert ": $1,200.00 by Friday." in match.after


def test_search_matches_image_page(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/scan.png", file_type="image")
    _add_image_page(conn, document_id, "Signed by John Doe on 2026-01-01")

    matches = search_indexed_content(conn, "john doe")

    assert len(matches) == 1
    assert matches[0].file_name == "scan.png"
    assert matches[0].page_number is None
    assert matches[0].total_pages is None
    assert matches[0].matched == "John Doe"


def test_search_excludes_removed_source(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/invoice.pdf")
    _add_pdf_page(conn, document_id, 1, "Total amount due: $1,200.00 by Friday.")
    conn.execute("UPDATE sources SET is_active = 0, status = 'removed' WHERE id = ?", (source_id,))
    conn.commit()

    matches = search_indexed_content(conn, "amount due")

    assert matches == []


def test_search_is_case_insensitive(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/letter.pdf")
    _add_pdf_page(conn, document_id, 1, "URGENT NOTICE")

    matches = search_indexed_content(conn, "urgent")

    assert len(matches) == 1


def test_search_returns_one_row_per_matching_page(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/report.pdf")
    _add_pdf_page(conn, document_id, 1, "budget overview")
    _add_pdf_page(conn, document_id, 2, "no match here")
    _add_pdf_page(conn, document_id, 3, "final budget numbers")

    matches = search_indexed_content(conn, "budget")

    assert len(matches) == 2
    assert [m.file_id for m in matches] == [document_id, document_id]
    assert [m.page_number for m in matches] == [1, 3]
    assert [m.total_pages for m in matches] == [3, 3]


def test_search_ignores_non_indexed_documents(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/pending.pdf", status="pending")
    _add_pdf_page(conn, document_id, 1, "confidential findings")

    matches = search_indexed_content(conn, "confidential")

    assert matches == []


def test_search_no_matches_returns_empty_list(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/notes.pdf")
    _add_pdf_page(conn, document_id, 1, "nothing relevant")

    assert search_indexed_content(conn, "unrelated term") == []


def test_search_empty_query_returns_empty_list(conn: sqlite3.Connection):
    assert search_indexed_content(conn, "") == []


def test_search_snippet_context_is_configurable(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/long.pdf")
    text = "x" * 100 + "TARGET" + "y" * 100
    _add_pdf_page(conn, document_id, 1, text)

    set_search_snippet_context_chars(conn, 10)
    matches = search_indexed_content(conn, "target")

    assert len(matches) == 1
    assert matches[0].before == "x" * 10
    assert matches[0].after == "y" * 10
    assert matches[0].truncated_before is True
    assert matches[0].truncated_after is True


def test_search_returns_duplicate_as_its_own_flagged_result(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    original_id = _add_document(conn, source_id, "/docs/original.pdf")
    _add_pdf_page(conn, original_id, 1, "Total amount due: $1,200.00 by Friday.")
    duplicate_id = _add_document(conn, source_id, "/docs/copy.pdf", duplicate_of_id=original_id)

    matches = search_indexed_content(conn, "amount due")

    assert len(matches) == 2
    by_file_id = {m.file_id: m for m in matches}
    assert by_file_id[original_id].duplicate_of_path is None
    assert by_file_id[duplicate_id].file_name == "copy.pdf"
    assert by_file_id[duplicate_id].duplicate_of_path == "/docs/original.pdf"
    assert by_file_id[duplicate_id].matched == "amount due"
    assert by_file_id[duplicate_id].total_pages == 1


def test_search_context_chars_argument_overrides_setting(conn: sqlite3.Connection):
    source_id = _add_source(conn)
    document_id = _add_document(conn, source_id, "/docs/long.pdf")
    text = "x" * 100 + "TARGET" + "y" * 100
    _add_pdf_page(conn, document_id, 1, text)

    matches = search_indexed_content(conn, "target", context_chars=5)

    assert matches[0].before == "x" * 5
    assert matches[0].after == "y" * 5
