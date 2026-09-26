"""Search across previously OCR-indexed content."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from vethuq_core.settings import get_search_snippet_context_chars


@dataclass(frozen=True)
class SearchMatch:
    """One matching page, split around its first match so a caller can highlight it."""

    file_id: int
    file_name: str
    file_path: str
    page_number: int | None
    total_pages: int | None
    before: str
    matched: str
    after: str
    truncated_before: bool
    truncated_after: bool
    duplicate_of_path: str | None


def _indexed_pages(
    conn: sqlite3.Connection,
) -> list[tuple[int, str, str, int | None, int, str | None]]:
    """Return `(document_id, file_path, ocr_text, page_number, canonical_id, duplicate_of_path)`.

    `canonical_id` is the id whose `pdf_pages`/`image_pages` rows actually hold
    the text - a duplicate document has none of its own, so it's the id of the
    original it matches; `duplicate_of_path` is that original's file path, or
    None if this document isn't a duplicate. A duplicate is thus returned as
    its own row here (with its own `document_id`/`file_path`), reusing the
    original's OCR text, so it still surfaces as its own search result.
    """
    pdf_rows = conn.execute(
        "SELECT di.id AS document_id, di.file_path AS file_path, pp.ocr_text AS ocr_text, "
        "pp.page_number AS page_number, "
        "COALESCE(di.duplicate_of_id, di.id) AS canonical_id, "
        "orig.file_path AS duplicate_of_path "
        "FROM document_index di "
        "JOIN pdf_pages pp ON pp.document_id = COALESCE(di.duplicate_of_id, di.id) "
        "JOIN sources s ON s.id = di.source_id "
        "LEFT JOIN document_index orig ON orig.id = di.duplicate_of_id "
        "WHERE di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
        "ORDER BY di.file_path, pp.page_number"
    ).fetchall()
    image_rows = conn.execute(
        "SELECT di.id AS document_id, di.file_path AS file_path, ip.ocr_text AS ocr_text, "
        "NULL AS page_number, "
        "COALESCE(di.duplicate_of_id, di.id) AS canonical_id, "
        "orig.file_path AS duplicate_of_path "
        "FROM document_index di "
        "JOIN image_pages ip ON ip.document_id = COALESCE(di.duplicate_of_id, di.id) "
        "JOIN sources s ON s.id = di.source_id "
        "LEFT JOIN document_index orig ON orig.id = di.duplicate_of_id "
        "WHERE di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
        "ORDER BY di.file_path"
    ).fetchall()
    return [
        (
            row["document_id"],
            row["file_path"],
            row["ocr_text"],
            row["page_number"],
            row["canonical_id"],
            row["duplicate_of_path"],
        )
        for row in (*pdf_rows, *image_rows)
    ]


def _pdf_page_counts(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        "SELECT document_id, COUNT(*) AS total FROM pdf_pages GROUP BY document_id"
    ).fetchall()
    return {row["document_id"]: row["total"] for row in rows}


def search_indexed_content(
    conn: sqlite3.Connection, query: str, *, context_chars: int | None = None
) -> list[SearchMatch]:
    """Search indexed OCR text for `query`, case-insensitively.

    Returns one `SearchMatch` per matching page, ordered by file path (pages of
    the same PDF stay in page order). Only successfully indexed documents are
    considered. When a page contains `query` more than once, only its first
    occurrence is used.
    """
    if not query:
        return []

    chars = context_chars if context_chars is not None else get_search_snippet_context_chars(conn)
    query_lower = query.lower()
    page_counts = _pdf_page_counts(conn)

    matches: list[SearchMatch] = []
    for (
        document_id,
        file_path,
        ocr_text,
        page_number,
        canonical_id,
        duplicate_of_path,
    ) in _indexed_pages(conn):
        text = ocr_text.replace("\n", " ")
        position = text.lower().find(query_lower)
        if position == -1:
            continue

        end = position + len(query)
        before_start = max(0, position - chars)
        after_end = min(len(text), end + chars)

        matches.append(
            SearchMatch(
                file_id=document_id,
                file_name=Path(file_path).name,
                file_path=file_path,
                page_number=page_number,
                total_pages=page_counts.get(canonical_id) if page_number is not None else None,
                before=text[before_start:position],
                matched=text[position:end],
                after=text[end:after_end],
                truncated_before=before_start > 0,
                truncated_after=after_end < len(text),
                duplicate_of_path=duplicate_of_path,
            )
        )

    matches.sort(key=lambda m: m.file_path)
    return matches
