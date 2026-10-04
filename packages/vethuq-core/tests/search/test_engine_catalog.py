import json

import pytest
from vethuq_core.paths import Paths
from vethuq_core.search import Search, SearchOptionError
from vethuq_core.search.engines import Ranking, SearchEngines
from vethuq_core.search.engines.catalog import SearchEngineCatalog
from vethuq_core.settings import SearchSettings
from vethuq_core.settings.filetypes import FileTypeSettings
from vethuq_core.storage import Storage
from vethuq_core.version import VersionInfo


@pytest.fixture
def only_like_and_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: tmp_path))
    (tmp_path / SearchEngineCatalog.SELECTION_FILENAME).write_text(
        json.dumps({"enabled": ["exact"]}), encoding="utf-8"
    )


class TestCatalog:
    def test_every_registered_engine_has_a_search_extra(self):
        ids = {e.id for e in SearchEngineCatalog.all()}
        assert ids == {e for e in SearchSettings.ENGINES if e != SearchSettings.ENGINE_ALL}
        assert all(e.extra == f"search-{e.id}" for e in SearchEngineCatalog.all())

    def test_like_is_the_default(self):
        assert [e.id for e in SearchEngineCatalog.all() if e.default] == ["like"]
        assert SearchEngineCatalog.all()[0].id == "like"

    def test_everything_is_enabled_without_a_selection(self):
        assert SearchEngineCatalog.selection() is None
        assert len(SearchEngineCatalog.enabled()) == len(SearchEngineCatalog.all())

    def test_selection_limits_engines_but_never_the_default(self, only_like_and_exact):
        assert [e.id for e in SearchEngineCatalog.enabled()] == ["like", "exact"]
        reason = SearchEngineCatalog.unavailable_reason(SearchEngineCatalog.get("fuzzy"))
        assert "not enabled" in reason


class TestDisabledEngines:
    def test_registry_refuses_and_lists_only_enabled(self, storage: Storage, only_like_and_exact):
        assert SearchEngines.available() == ["exact", "like"]
        with pytest.raises(ValueError, match="not enabled"):
            SearchEngines.get(storage, "fuzzy")

    def test_all_engines_search_skips_disabled_ones(self, only_like_and_exact):
        assert Ranking.active_tiers() == ("exact", "like")

    def test_asking_for_a_disabled_engine_is_an_option_error(
        self, storage: Storage, only_like_and_exact
    ):
        with pytest.raises(SearchOptionError) as excinfo:
            Search.resolve_options(storage, "fuzzy", None)
        assert excinfo.value.option == "engine"

    def test_a_saved_default_that_is_disabled_falls_back_to_all(
        self, storage: Storage, only_like_and_exact
    ):
        SearchSettings.set_engine(storage, "fuzzy")
        assert Search.resolve_options(storage, None, None).engine == "all"


class TestRecorded:
    def test_installed_engines_are_stored(self, storage: Storage):
        recorded = FileTypeSettings.record_installed_engines(storage)
        assert "search-like" in recorded
        assert FileTypeSettings.get_installed_engines(storage) == recorded

    def test_version_lists_search_engines(self):
        assert "search-like" in dict(VersionInfo.rows())["Search engines"]
