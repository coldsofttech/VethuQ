import pytest
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage


class TestResolveOptions:
    def test_falls_back_to_settings(self, storage: Storage):
        assert Search.resolve_options(storage, None, None) == ("like", False, None)

        SearchSettings.set_case_sensitive(storage, True)
        assert Search.resolve_options(storage, None, None) == ("like", True, None)
        assert Search.resolve_options(storage, "like", False) == ("like", False, None)

        # A stored preference the engine can't honour is dropped, not an error...
        assert Search.resolve_options(storage, "exact", None) == ("exact", True, None)
        assert Search.resolve_options(storage, "full-text", None) == ("full-text", False, None)
        SearchSettings.set_engine(storage, "full-text")
        assert Search.resolve_options(storage, None, None) == ("full-text", False, None)

        # ...while fuzzy honours case and always resolves a threshold (default: balanced).
        assert Search.resolve_options(storage, "fuzzy", None) == ("fuzzy", True, 0.8)
        assert Search.resolve_options(storage, "fuzzy", False, 0.7) == ("fuzzy", False, 0.7)
        assert Search.resolve_options(storage, "fuzzy", False, "loose") == ("fuzzy", False, 0.65)

    def test_rejects_what_the_engine_cannot_honour(self, storage: Storage):
        with pytest.raises(SearchOptionError) as unknown:
            Search.resolve_options(storage, "nope", None)
        assert unknown.value.option == "engine"

        with pytest.raises(SearchOptionError) as full_text:
            Search.resolve_options(storage, "full-text", True)
        assert full_text.value.option == "case_sensitive"

        with pytest.raises(SearchOptionError) as exact:
            Search.resolve_options(storage, "exact", False)
        assert exact.value.option == "case_sensitive"

    def test_threshold_rules(self, storage: Storage):
        SearchSettings.set_fuzzy_threshold(storage, "strict")
        assert Search.resolve_options(storage, "fuzzy", False).threshold == 0.9

        for engine in ("like", "exact", "full-text"):
            with pytest.raises(SearchOptionError) as excinfo:
                Search.resolve_options(storage, engine, None, 0.8)
            assert excinfo.value.option == "threshold"
        for bad in (0, -0.1, 1.5, "nope"):
            with pytest.raises(SearchOptionError) as excinfo:
                Search.resolve_options(storage, "fuzzy", None, bad)
            assert excinfo.value.option == "threshold"

    @pytest.mark.parametrize("engine", ["like", "exact", "full-text"])
    def test_non_fuzzy_engines_reject_a_threshold(self, storage: Storage, engine: str):
        with pytest.raises(ValueError, match="only fuzzy"):
            Search.indexed_content(storage, "museum", engine=engine, threshold=0.8)
