"""Search across previously OCR-indexed content."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from vethuq_core.db.queries import Document
from vethuq_core.settings import SearchSettings


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


@dataclass(frozen=True)
class FileMatch:
    """One file with at least one matching page - `SearchMatch`es collapsed per file."""

    file_id: int
    file_name: str
    file_path: str
    is_duplicate: bool


class Search:
    @staticmethod
    def _like_pattern(query: str) -> str:
        """Escape `query` for use as a `LIKE '%...%'` pattern, so its `%`/`_`/`\\` are literal."""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    @staticmethod
    def _indexed_pages(
        conn: sqlite3.Connection, query: str
    ) -> list[tuple[int, str, str, int | None, int, str | None]]:
        """Return rows of `(document_id, file_path, ocr_text, page_number, canonical_id,
        duplicate_of_path)` for every indexed page whose `ocr_text` may contain `query`.

        Narrowed down via `pdf_pages_fts`/`image_pages_fts`/`office_pages_fts` - trigram-tokenized
        FTS5 indexes kept in sync with `pdf_pages`/`image_pages`/`office_pages` by triggers (see
        `vethuq_core.db.connection`) - queried with `LIKE` rather than `MATCH` so
        matching stays substring-based (e.g. "arge" still matches "large") and
        case-insensitive, same as before this index existed, just without a full
        Python-side scan of every indexed page's text.

        `canonical_id` is the `document_index.id` whose `pdf_pages`/`image_pages`
        rows actually hold the text - among every row sharing this one's logical
        document (`document_index.document_id`), exactly one carries OCR pages of
        its own (the rest are checksum links with none); `duplicate_of_path` is
        that carrier's file path, or None if this row is the carrier itself. A
        duplicate is thus returned as its own row here (with its own
        `document_id`/`file_path`), reusing the carrier's OCR text, so it still
        surfaces as its own search result.
        """
        like_pattern = Search._like_pattern(query)
        pdf_rows = Document.search_indexed_pdf_pages(conn, like_pattern)
        image_rows = Document.search_indexed_image_pages(conn, like_pattern)
        office_rows = Document.search_indexed_office_pages(conn, like_pattern)
        return [
            (
                row["document_id"],
                row["file_path"],
                row["ocr_text"],
                row["page_number"],
                row["canonical_id"],
                row["duplicate_of_path"],
            )
            for row in (*pdf_rows, *image_rows, *office_rows)
        ]

    @staticmethod
    def _pdf_page_counts(conn: sqlite3.Connection) -> dict[int, int]:
        return {row["document_id"]: row["total"] for row in Document.get_pdf_page_counts(conn)}

    @staticmethod
    def indexed_content(
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

        chars = (
            context_chars
            if context_chars is not None
            else SearchSettings.get_snippet_context_chars(conn)
        )
        query_lower = query.lower()
        page_counts = Search._pdf_page_counts(conn)

        matches: list[SearchMatch] = []
        for (
            document_id,
            file_path,
            ocr_text,
            page_number,
            canonical_id,
            duplicate_of_path,
        ) in Search._indexed_pages(conn, query):
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

    @staticmethod
    def files(
        conn: sqlite3.Connection, query: str, *, context_chars: int | None = None
    ) -> list[FileMatch]:
        """Search like `indexed_content`, but return one `FileMatch` per matching file.

        Files keep the order of their first matching page (so, by file path).
        """
        files: dict[int, FileMatch] = {}
        for match in Search.indexed_content(conn, query, context_chars=context_chars):
            files.setdefault(
                match.file_id,
                FileMatch(
                    file_id=match.file_id,
                    file_name=match.file_name,
                    file_path=match.file_path,
                    is_duplicate=match.duplicate_of_path is not None,
                ),
            )
        return list(files.values())
