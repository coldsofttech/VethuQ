"""Search engines behind a single interface - see `base.SearchEngine`."""

from vethuq_core.search.engines.base import (
    FallbackSearchEngine,
    SearchEngine,
    SearchEngineUnavailable,
    SearchMatch,
    SearchQueryError,
)
from vethuq_core.search.engines.registry import SearchEngines

__all__ = [
    "FallbackSearchEngine",
    "SearchEngine",
    "SearchEngineUnavailable",
    "SearchEngines",
    "SearchMatch",
    "SearchQueryError",
]
