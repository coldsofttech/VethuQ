"""Engine registry: which `SearchEngine` implementations exist and how they're built."""

from __future__ import annotations

from collections.abc import Callable

from vethuq_core.search.engines.base import SearchEngine
from vethuq_core.storage import Storage

# Builds an engine bound to a connection.
EngineFactory = Callable[[Storage], SearchEngine]


class SearchEngines:
    DEFAULT = "like"

    _factories: dict[str, EngineFactory] = {}

    @staticmethod
    def register(name: str, factory: EngineFactory) -> None:
        """Make a search engine available under `name`, replacing any existing one."""
        SearchEngines._factories[name] = factory

    @staticmethod
    def get(storage: Storage, name: str | None = None) -> SearchEngine:
        """Build the engine registered as `name` (default `SearchEngines.DEFAULT`) on `storage`."""
        key = name or SearchEngines.DEFAULT
        try:
            factory = SearchEngines._factories[key]
        except KeyError:
            raise ValueError(
                f"Unknown search engine {key!r}; available: {sorted(SearchEngines._factories)}"
            ) from None
        return factory(storage)

    @staticmethod
    def _like_factory(storage: Storage) -> SearchEngine:
        from vethuq_core.search.engines.like import LikeSearchEngine

        return LikeSearchEngine(storage)

    @staticmethod
    def _lexical_factory(storage: Storage) -> SearchEngine:
        from vethuq_core.search.engines.lexical import LexicalSearchEngine

        return LexicalSearchEngine(storage)

    @staticmethod
    def _exact_factory(storage: Storage) -> SearchEngine:
        from vethuq_core.search.engines.exact import ExactSearchEngine

        return ExactSearchEngine(storage)

    @staticmethod
    def _fulltext_factory(storage: Storage) -> SearchEngine:
        from vethuq_core.search.engines.fulltext import FullTextSearchEngine

        return FullTextSearchEngine(storage)

    @staticmethod
    def _fuzzy_factory(storage: Storage) -> SearchEngine:
        from vethuq_core.search.engines.fuzzy import FuzzySearchEngine

        return FuzzySearchEngine(storage)

    @staticmethod
    def _proximity_factory(storage: Storage) -> SearchEngine:
        from vethuq_core.search.engines.proximity import ProximitySearchEngine

        return ProximitySearchEngine(storage)

    @staticmethod
    def _leetspeak_factory(storage: Storage) -> SearchEngine:
        from vethuq_core.search.engines.leetspeak import LeetspeakSearchEngine

        return LeetspeakSearchEngine(storage)

    @staticmethod
    def available() -> list[str]:
        """Names of the registered engines, sorted."""
        return sorted(SearchEngines._factories)


SearchEngines.register("like", SearchEngines._like_factory)
SearchEngines.register("lexical", SearchEngines._lexical_factory)
SearchEngines.register("exact", SearchEngines._exact_factory)
SearchEngines.register("full-text", SearchEngines._fulltext_factory)
SearchEngines.register("fuzzy", SearchEngines._fuzzy_factory)
SearchEngines.register("proximity", SearchEngines._proximity_factory)
SearchEngines.register("leetspeak", SearchEngines._leetspeak_factory)
