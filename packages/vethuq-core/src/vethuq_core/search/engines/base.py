"""The search-engine interface: what `vethuq_core.search` needs from "a search engine".

Callers depend only on this module and `vethuq_core.search.engines.registry`,
never on a concrete engine, so adding a lexical index (e.g. FTS5 `MATCH`)
means adding one `SearchEngine` implementation and registering it. Engines
coexist behind the registry - selectable by name, or chained with
`FallbackSearchEngine` - rather than replacing one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchMatch:
    """One occurrence of a query on a page, split around the match so a caller can highlight it."""

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


class SearchEngineUnavailable(Exception):
    """Raised by an engine that can't serve queries right now (e.g. its index is missing).

    `FallbackSearchEngine` catches this and tries the next engine.
    """


class SearchEngine(Protocol):
    """Finds indexed pages matching a query. Implement this to add a new search engine.

    Engines are bound to a database connection at construction (see
    `vethuq_core.search.engines.registry.SearchEngines.get`).
    """

    @property
    def name(self) -> str:
        """Engine label, e.g. `like`."""
        ...

    def search(self, query: str, *, context_chars: int | None = None) -> list[SearchMatch]:
        """Return one `SearchMatch` per occurrence of `query`, ordered by file path.

        `context_chars` is the snippet context either side of the match;
        None means the user's setting. An empty `query` matches nothing.
        May raise `SearchEngineUnavailable`.
        """
        ...


class FallbackSearchEngine:
    """Tries `primary`; if it raises `SearchEngineUnavailable`, answers from `fallback`."""

    def __init__(self, primary: SearchEngine, fallback: SearchEngine) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def name(self) -> str:
        return f"{self._primary.name}->{self._fallback.name}"

    def search(self, query: str, *, context_chars: int | None = None) -> list[SearchMatch]:
        try:
            return self._primary.search(query, context_chars=context_chars)
        except SearchEngineUnavailable:
            return self._fallback.search(query, context_chars=context_chars)
