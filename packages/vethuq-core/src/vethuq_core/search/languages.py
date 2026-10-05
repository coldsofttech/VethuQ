"""Narrowing search results to the language the pages were read in (`--lang`)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from vethuq_core.languages import LanguageSelection, UnknownLanguageError
from vethuq_core.search.engines import PageResult, SearchMatch
from vethuq_core.storage import Storage


class SearchLanguageError(ValueError):
    """`--lang` named a language VethuQ does not know."""


class SearchLanguages:
    DEFAULT = "en"
    _CHUNK = 400  # file ids per query, well under SQLite's variable limit

    @staticmethod
    def parse(languages: str | Iterable[str] | None) -> list[str] | None:
        """The language ids to keep, or None for no filter (nothing given, or `auto`).

        Any language VethuQ knows may be asked for, installed or not: pages read while a language
        was installed stay searchable after it is removed.
        """
        try:
            ids = LanguageSelection.parse(languages)
        except UnknownLanguageError as exc:
            raise SearchLanguageError(str(exc)) from exc
        return None if ids is None or ids == [LanguageSelection.AUTO] else ids

    @staticmethod
    def _page_languages(storage: Storage, file_ids: Sequence[int]) -> dict[tuple, set[str]]:
        """`(file_id, page_number)` -> the languages the page was read in. A page written before
        languages were recorded was read in English."""
        found: dict[tuple, set[str]] = {}
        ids = sorted(set(file_ids))
        for start in range(0, len(ids), SearchLanguages._CHUNK):
            for row in storage.get_page_languages(ids[start : start + SearchLanguages._CHUNK]):
                langs = {part for part in (row["ocr_langs"] or "").split(",") if part}
                if row["language"]:
                    langs.add(row["language"])
                found.setdefault((row["file_id"], row["page_number"]), set()).update(
                    langs or {SearchLanguages.DEFAULT}
                )
        return found

    @staticmethod
    def filter_matches(
        storage: Storage, matches: list[SearchMatch], languages: Sequence[str] | None
    ) -> list[SearchMatch]:
        """The matches on pages that were read in any of `languages`, in their order.

        A page read in two languages (English plus Telugu) is kept by either. `languages` of
        None keeps everything, and nothing is looked up.
        """
        if languages is None:
            return matches
        wanted = set(languages)
        pages = SearchLanguages._page_languages(storage, [m.file_id for m in matches])
        return [m for m in matches if pages.get((m.file_id, m.page_number), set()) & wanted]

    @staticmethod
    def filter_pages(
        storage: Storage, pages: list[PageResult], languages: Sequence[str] | None
    ) -> list[PageResult]:
        """Like `filter_matches`, for the pages `Search.indexed_pages` ranks."""
        if languages is None:
            return pages
        wanted = set(languages)
        read = SearchLanguages._page_languages(storage, [p.file_id for p in pages])
        return [p for p in pages if read.get((p.file_id, p.page_number), set()) & wanted]
