"""Search engines behind a single interface - see `base.SearchEngine`."""

from vethuq_core.search.engines.base import (
    FallbackSearchEngine,
    SearchEngine,
    SearchEngineUnavailable,
    SearchMatch,
    SearchQueryError,
)
from vethuq_core.search.engines.ranking import PageResult, Ranking
from vethuq_core.search.engines.registry import SearchEngines

__all__ = [
    "FallbackSearchEngine",
    "PageResult",
    "Ranking",
    "SearchEngine",
    "SearchEngineUnavailable",
    "SearchEngines",
    "SearchMatch",
    "SearchQueryError",
]
