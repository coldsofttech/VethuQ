import pytest
from vethuq_core.search.engines import (
    FallbackSearchEngine,
    SearchEngines,
    SearchEngineUnavailable,
)
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class TestSearchEngines:
    def test_registry_default_and_unknown(self, storage: Storage):
        assert SearchEngines.get(storage).name == "like"
        with pytest.raises(ValueError, match="Unknown search engine"):
            SearchEngines.get(storage, "nope")

    def test_fallback_engine_uses_fallback_when_primary_unavailable(self, storage: Storage):
        class Broken:
            name = "broken"

            def search(
                self,
                query,
                *,
                context_chars=None,
                case_sensitive=False,
                threshold=None,
                distance=None,
                level=None,
            ):
                raise SearchEngineUnavailable

        engine = FallbackSearchEngine(Broken(), SearchEngines.get(storage))
        assert engine.name == "broken->like"
        assert engine.search("") == []


class TestEngineRegistry:
    def test_lists_all_engines_and_matches_settings(self):
        # `all` isn't an engine: it runs the others.
        engines = [e for e in SearchSettings.ENGINES if e != SearchSettings.ENGINE_ALL]
        assert SearchEngines.available() == sorted(engines)
