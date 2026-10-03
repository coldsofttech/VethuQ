"""The `like` search engine: substring matching over OCR text, mid-word included."""

from __future__ import annotations

from collections.abc import Iterator

from vethuq_core.search.engines.base import SearchMatch
from vethuq_core.search.engines.common import SearchEngineHelpers
from vethuq_core.storage import Storage


class LikeSearchEngine:
    """`SearchEngine` that finds `query` as a substring anywhere in a page's text.

    Case-insensitive unless `case_sensitive` is set, and not word-aware: `mus`
    finds "Museum" and `arge` finds "large". Occurrences don't overlap.
    """

    name = "like"

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def search(
        self,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
    ) -> list[SearchMatch]:
        SearchEngineHelpers.require_no_threshold(self.name, threshold)
        return SearchEngineHelpers.search_substring_pages(
            self._storage,
            query,
            lambda text: LikeSearchEngine._occurrences(text, query, case_sensitive=case_sensitive),
            context_chars=context_chars,
        )

    @staticmethod
    def _occurrences(text: str, query: str, *, case_sensitive: bool) -> Iterator[tuple[int, int]]:
        """Yield the non-overlapping `(start, end)` spans of `query` in `text`."""
        haystack, needle = (text, query) if case_sensitive else (text.lower(), query.lower())
        position = haystack.find(needle)
        while position != -1:
            end = position + len(query)
            yield position, end
            position = haystack.find(needle, end)
