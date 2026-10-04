"""Helpers shared by the search engines: page counts, snippet building and result ordering."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path

from vethuq_core.languages import Scripts
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
    def require_no_level(engine: str, level: str | None) -> None:
        """Reject a leetspeak `level` for an engine that doesn't read look-alikes."""
        if level is not None:
            raise ValueError(
                f"The {engine} engine has no leetspeak level; only like and noise-fuzzy do."
            )

    @staticmethod
    def require_no_noise(engine: str, noise: str | None) -> None:
        """Reject a noise level for an engine that isn't noise-fuzzy."""
        if noise is not None:
            raise ValueError(f"The {engine} engine has no noise level; only noise-fuzzy does.")

    @staticmethod
    def require_no_unicode(engine: str, unicode: str | None) -> None:
        """Reject a Unicode level for an engine that has no Unicode normalization to set."""
        if unicode is not None:
            raise ValueError(
                f"The {engine} engine has no unicode setting; only like, exact, fuzzy and "
                "noise-fuzzy do."
            )

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
        """Build the `SearchMatch` for `text[start:end]`, with `chars` of context either side.

        Context never begins or ends in the middle of a syllable: a Telugu vowel sign is kept
        with its letter, so a snippet does not start on a sign with no letter or lose the sign
        of its last letter.
        """
        before_start = max(0, start - chars)
        after_end = min(len(text), end + chars)
        while before_start > 0 and SearchEngineHelpers._is_sign(text[before_start]):
            before_start -= 1
        while after_end < len(text) and SearchEngineHelpers._is_sign(text[after_end]):
            after_end += 1
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
    def _is_sign(char: str) -> bool:
        """Whether `char` is a combining mark of a script whose marks are part of its words (a
        Telugu vowel sign): it can't stand without the letter before it. Accents of other
        scripts are not, so snippets of other text are cut exactly where they always were."""
        return unicodedata.category(char)[0] == "M" and Scripts.keeps_marks(char)

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
    def norm_match(text: str) -> str | None:
        """`text` as a quoted FTS5 phrase for the trigram index over the normalized text, or
        None if its normalized form is under 3 characters (every page is then a candidate).

        The index holds each page's text folded as coarsely as any normalization does, so a
        page that has `text` at any normalization level has this phrase in it - an
        approximation only at the edges of combining characters.
        """
        from vethuq_core.search.normalizers import Normalizers

        return SearchEngineHelpers.trigram_match(Normalizers.index_form(text))

    @staticmethod
    def search_substring_pages(
        storage: Storage,
        query: str,
        find: Callable[[str], Iterable[tuple[int, int]]],
        *,
        context_chars: int | None,
        engine: str,
        candidates: str = "raw",
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

        `candidates` says which index narrows them: `"raw"` (the trigram index over the text, for
        text as it is), `"norm"` (the one over the text folded as coarsely as any normalization
        does - see `Normalizers.index_form` - for a query that is normalized) or `"none"`.
        """
        if not query:
            return []

        chars = SearchEngineHelpers.resolve_context_chars(storage, context_chars)
        page_counts = SearchEngineHelpers.pdf_page_counts(storage)
        if candidates == "raw":
            pattern = SearchEngineHelpers.like_pattern(query)
            match_expr = SearchEngineHelpers.trigram_match(query)
            rows = (
                *storage.search_indexed_pdf_pages(pattern, match_expr),
                *storage.search_indexed_image_pages(pattern, match_expr),
            )
        elif candidates == "norm":
            expression = SearchEngineHelpers.norm_match(query)
            rows = (
                *storage.search_norm_candidate_pdf_pages(expression),
                *storage.search_norm_candidate_image_pages(expression),
            )
        else:
            rows = (
                *storage.search_candidate_pdf_pages(None),
                *storage.search_candidate_image_pages(None),
            )

        matches: list[SearchMatch] = []
        for row in rows:
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
