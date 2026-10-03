"""The `LIKE`-based search engine: substring, case-insensitive matching over OCR text."""

from __future__ import annotations

from pathlib import Path

from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class LikeSearchEngine:
    """`SearchEngine` backed by `LIKE` queries against the trigram FTS tables."""

    name = "like"

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def search(self, query: str, *, context_chars: int | None = None) -> list[SearchMatch]:
        return LikeSearchEngine._search_pages(self._storage, query, context_chars=context_chars)

    @staticmethod
    def _like_pattern(query: str) -> str:
        """Escape `query` for use as a `LIKE '%...%'` pattern, so its `%`/`_`/`\\` are literal."""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    @staticmethod
    def _indexed_pages(
        storage: Storage, query: str
    ) -> list[tuple[int, str, str, int | None, int, str | None]]:
        """Return rows of `(document_id, file_path, ocr_text, page_number, canonical_id,
        duplicate_of_path)` for every indexed page whose `ocr_text` may contain `query`.

        Narrowed down via `pdf_pages_fts`/`image_pages_fts` - trigram-tokenized FTS5
        indexes kept in sync with `pdf_pages`/`image_pages` by triggers (see
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
        like_pattern = LikeSearchEngine._like_pattern(query)
        pdf_rows = storage.search_indexed_pdf_pages(like_pattern)
        image_rows = storage.search_indexed_image_pages(like_pattern)
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

    @staticmethod
    def _pdf_page_counts(storage: Storage) -> dict[int, int]:
        return {
            row["document_id"]: row["total"] for row in storage.get_pdf_page_counts_by_document()
        }

    @staticmethod
    def _search_pages(
        storage: Storage, query: str, *, context_chars: int | None = None
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
            else SearchSettings.get_snippet_context_chars(storage)
        )
        query_lower = query.lower()
        page_counts = LikeSearchEngine._pdf_page_counts(storage)

        matches: list[SearchMatch] = []
        for (
            document_id,
            file_path,
            ocr_text,
            page_number,
            canonical_id,
            duplicate_of_path,
        ) in LikeSearchEngine._indexed_pages(storage, query):
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
