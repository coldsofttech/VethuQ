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
    source: str = "ocr"  # 'native', 'ocr' or 'mixed' - how the page's text was obtained
    score: float | None = None  # relevance (higher is better); only ranked engines set it
    start: int | None = None  # where the match starts in the page's text (newlines as spaces)
    end: int | None = None  # ...and ends
    engine: str | None = None  # the engine that found it, or the strictest one that did
    matched_by: tuple[str, ...] = ()  # every engine that found it, strictest first (`all` only)
    # The normalizations it needed to match as typed (`accents`, `look-alike`); `all` only
    modifiers: tuple[str, ...] = ()


class SearchQueryError(ValueError):
    """The query itself can't be searched by this engine (e.g. too few terms for `proximity`)."""


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

    def search(
        self,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> list[SearchMatch]:
        """Return one `SearchMatch` per occurrence of `query`.

        Ordered by file path, unless the engine ranks results (then by
        relevance, best first - see `SearchMatch.score`). `context_chars` is
        the snippet context either side of the match; None means the user's
        setting. `case_sensitive` asks for a case-sensitive match: engines that
        always match case-sensitively ignore it, and an engine that can't
        honour it raises `ValueError`. `threshold` is the minimum word
        similarity (0-1] a tolerant engine accepts, None meaning the user's
        setting; an engine that isn't tolerant raises `ValueError` if given
        one. `distance` is the most words a `proximity` search allows between
        its first and last term, None meaning the user's setting; other engines
        raise `ValueError` if given one. `level` is the leetspeak normalization's level
        (`SearchSettings.LEETSPEAK_LEVELS`), None meaning the user's setting; other engines
        raise `ValueError` if given one. `noise` is the noise-fuzzy engine's noise level
        (`SearchSettings.NOISE_LEVELS`), None meaning the user's setting; other engines raise
        `ValueError` if given one. `unicode` is the Unicode normalization (`off`, `basic` or
        `full`) of the engines that take one (`like`, `exact`, `fuzzy`, `noise-fuzzy`); the others
        raise `ValueError` if given one. An empty `query` matches nothing, and a
        query an engine can't search raises `SearchQueryError`. May raise
        `SearchEngineUnavailable`.
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

    def search(
        self,
        query: str,
        *,
        context_chars: int | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> list[SearchMatch]:
        try:
            return self._primary.search(
                query,
                context_chars=context_chars,
                case_sensitive=case_sensitive,
                threshold=threshold,
                distance=distance,
                level=level,
                noise=noise,
                unicode=unicode,
            )
        except SearchEngineUnavailable:
            return self._fallback.search(
                query,
                context_chars=context_chars,
                case_sensitive=case_sensitive,
                threshold=threshold,
                distance=distance,
                level=level,
                noise=noise,
                unicode=unicode,
            )
