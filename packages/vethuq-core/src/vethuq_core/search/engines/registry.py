"""Engine registry: which `SearchEngine` implementations exist and how they're built."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from vethuq_core.search.engines.base import SearchEngine

# Builds an engine bound to a connection.
EngineFactory = Callable[[sqlite3.Connection], SearchEngine]


class SearchEngines:
    DEFAULT = "like"

    _factories: dict[str, EngineFactory] = {}

    @staticmethod
    def register(name: str, factory: EngineFactory) -> None:
        """Make a search engine available under `name`, replacing any existing one."""
        SearchEngines._factories[name] = factory

    @staticmethod
    def get(conn: sqlite3.Connection, name: str | None = None) -> SearchEngine:
        """Build the engine registered as `name` (default `SearchEngines.DEFAULT`) on `conn`."""
        key = name or SearchEngines.DEFAULT
        try:
            factory = SearchEngines._factories[key]
        except KeyError:
            raise ValueError(
                f"Unknown search engine {key!r}; available: {sorted(SearchEngines._factories)}"
            ) from None
        return factory(conn)

    @staticmethod
    def _like_factory(conn: sqlite3.Connection) -> SearchEngine:
        from vethuq_core.search.engines.like import LikeSearchEngine

        return LikeSearchEngine(conn)


SearchEngines.register("like", SearchEngines._like_factory)
