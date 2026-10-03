"""Helpers shared by the search engines: page counts, snippet building and result ordering."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class SearchEngineHelpers:
    @staticmethod
    def resolve_context_chars(storage: Storage, context_chars: int | None) -> int:
        """`context_chars` if given, else the user's snippet-context setting."""
        if context_chars is not None:
            return context_chars
        return SearchSettings.get_snippet_context_chars(storage)

    @staticmethod
    def require_no_threshold(engine: str, threshold: float | None) -> None:
        """Reject a similarity `threshold` for an engine that isn't fuzzy."""
        if threshold is not None:
            raise ValueError(f"The {engine} engine has no similarity threshold; only fuzzy does.")

    @staticmethod
    def require_no_distance(engine: str, distance: int | None) -> None:
        """Reject a word `distance` for an engine that isn't proximity."""
        if distance is not None:
            raise ValueError(f"The {engine} engine has no word distance; only proximity does.")

    @staticmethod
    def pdf_page_counts(storage: Storage) -> dict[int, int]:
        """Total page count of every PDF with OCR pages, keyed by its carrier document id."""
        return {
            row["document_id"]: row["total"] for row in storage.get_pdf_page_counts_by_document()
        }

    @staticmethod
    def build_match(
        *,
        document_id: int,
        file_path: str,
        page_number: int | None,
        total_pages: int | None,
        duplicate_of_path: str | None,
        source: str,
        text: str,
        start: int,
        end: int,
        chars: int,
        engine: str,
        score: float | None = None,
    ) -> SearchMatch:
        """Build the `SearchMatch` for `text[start:end]`, with `chars` of context either side."""
        before_start = max(0, start - chars)
        after_end = min(len(text), end + chars)
        return SearchMatch(
            file_id=document_id,
            file_name=Path(file_path).name,
            file_path=file_path,
            page_number=page_number,
            total_pages=total_pages,
            before=text[before_start:start],
            matched=text[start:end],
            after=text[end:after_end],
            truncated_before=before_start > 0,
            truncated_after=after_end < len(text),
            duplicate_of_path=duplicate_of_path,
            source=source,
            score=score,
            start=start,
            end=end,
            engine=engine,
        )

    @staticmethod
    def like_pattern(query: str) -> str:
        """Escape `query` for use as a `LIKE '%...%'` pattern, so its `%`/`_`/`\\` are literal."""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    # Shortest query the trigram index can serve; shorter ones fall back to `LIKE`.
    TRIGRAM_MIN_CHARS = 3

    @staticmethod
    def trigram_match(query: str) -> str | None:
        """`query` as a quoted FTS5 phrase for the trigram index, or None if under 3 characters.

        The trigram tokenizer matches a phrase as a case-insensitive substring, so
        quoting (with `"` doubled) makes the query literal text, never FTS5 syntax.
        """
        if len(query) < SearchEngineHelpers.TRIGRAM_MIN_CHARS:
            return None
        return '"' + query.replace('"', '""') + '"'

    @staticmethod
    def search_substring_pages(
        storage: Storage,
        query: str,
        find: Callable[[str], Iterable[tuple[int, int]]],
        *,
        context_chars: int | None,
        engine: str,
    ) -> list[SearchMatch]:
        """Find `query` on indexed pages, one `SearchMatch` per span `find` yields for a page.

        Candidate pages are narrowed with an FTS5 `MATCH` over the trigram-tokenized
        `pdf_pages_trigram`/`image_pages_trigram` indexes (kept in sync with
        `pdf_pages`/`image_pages` by triggers - see `vethuq_core.db.connection`),
        so a query landing mid-word still finds its page, without a full
        Python-side scan of every indexed page. Only a query too short for the
        trigram index (under 3 characters) falls back to `LIKE`. That narrowing is
        case-insensitive and a superset of every substring-based engine's
        matches, so `find` - which receives each candidate page's text with
        newlines flattened to spaces, and returns the `(start, end)` spans it
        accepts - has the final say on case and word boundaries.

        A duplicate document (a checksum link to a carrier that holds the OCR
        pages) is returned as its own row, reusing the carrier's text, so it still
        surfaces as its own search result. Ordered by file path (pages of the same
        PDF in page order, occurrences within a page in text order).
        """
        if not query:
            return []

        chars = SearchEngineHelpers.resolve_context_chars(storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(storage)
        pattern = SearchEngineHelpers.like_pattern(query)
        match_expr = SearchEngineHelpers.trigram_match(query)

        matches: list[SearchMatch] = []
        for row in (
            *storage.search_indexed_pdf_pages(pattern, match_expr),
            *storage.search_indexed_image_pages(pattern, match_expr),
        ):
            page_number = row["page_number"]
            text = row["ocr_text"].replace("\n", " ")
            total_pages = page_counts.get(row["canonical_id"]) if page_number is not None else None
            for start, end in find(text):
                matches.append(
                    SearchEngineHelpers.build_match(
                        document_id=row["document_id"],
                        file_path=row["file_path"],
                        page_number=page_number,
                        total_pages=total_pages,
                        duplicate_of_path=row["duplicate_of_path"],
                        source=row["source"],
                        text=text,
                        start=start,
                        end=end,
                        chars=chars,
                        engine=engine,
                    )
                )

        matches.sort(key=lambda m: m.file_path)
        return matches
