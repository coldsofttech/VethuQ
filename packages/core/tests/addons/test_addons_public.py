from __future__ import annotations

import sys

import pytest

import vethuq
from tests.addons_factory import AddonFactory
from vethuq.addons import AddonInfo, Addons, AddonSettings, AddonStatus


@pytest.fixture
def folder(tmp_path, monkeypatch):
    path = tmp_path / "site"
    path.mkdir()
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield path
    AddonFactory.forget("vethuq_addon_dummy")


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(tmp_path / "vethuq.db") as client:
        yield client


class TestWithoutAddons:
    def test_nothing_is_installed(self, client):
        assert isinstance(client.addons, Addons)
        assert client.addons.list() == []
        assert client.addons.get("backup") is None
        assert not client.addons.is_installed("backup")

    def test_importing_a_missing_addon_raises_module_not_found(self, client):
        with pytest.raises(ModuleNotFoundError):
            from vethuq.addons.nothing import Nothing  # noqa: F401

    def test_the_database_works_without_addons(self, client):
        assert client.sources.list() == []

    def test_listing_addons_does_not_create_the_database(self, tmp_path):
        client = vethuq.VethuQ(tmp_path / "x" / "vethuq.db")
        client.addons.list()
        assert not (tmp_path / "x").exists()


class TestWithAnAddon:
    def test_it_is_listed_as_loaded(self, folder, client):
        AddonFactory.install(folder)
        info = client.addons.get("dummy")
        assert info == AddonInfo("dummy", "vethuq-addon-dummy", "1.2.3", AddonStatus.LOADED)
        assert client.addons.is_installed("dummy")

    def test_its_public_class_imports_from_vethuq_addons(self, folder, client):
        module = AddonFactory.install(folder)
        client.addons.list()
        from vethuq.addons.dummy import Dummy

        import importlib

        assert Dummy is importlib.import_module(module).Dummy
        assert Dummy(client).client is client

    def test_the_alias_is_the_real_module(self, folder, client):
        AddonFactory.install(folder)
        client.addons.list()
        import importlib

        alias = importlib.import_module("vethuq.addons.dummy")
        assert alias is importlib.import_module("vethuq_addon_dummy")

    def test_on_open_runs_when_the_database_opens(self, folder, client):
        module = AddonFactory.install(folder)
        client.sources.list()
        events = sys.modules[module].EVENTS
        assert ("open", "none") in events
        assert client.addons.settings("dummy").get("seen") == "yes"

    def test_before_migration_runs_when_an_older_schema_is_opened(self, folder, tmp_path):
        import sqlite3

        module = AddonFactory.install(folder)
        path = tmp_path / "old.db"
        with vethuq.VethuQ(path) as first:
            first.sources.list()
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE schema_version SET version = 0")
        sys.modules[module].EVENTS.clear()
        from vethuq._db import _Schema

        original = _Schema.VERSION
        try:
            _Schema.VERSION = original + 1
            from vethuq._db import _Migration

            _Migration.STEPS[original] = lambda connection: None
            with vethuq.VethuQ(path) as second:
                second.sources.list()
        finally:
            _Schema.VERSION = original
            _Migration.STEPS.pop(original, None)
        assert any(event[0] == "migrate" for event in sys.modules[module].EVENTS)

    def test_a_failing_hook_does_not_stop_the_database(self, folder, client):
        AddonFactory.install(folder, open_extra="raise RuntimeError('boom')")
        assert client.sources.list() == []

    def test_info_serialises(self, folder, client):
        AddonFactory.install(folder)
        info = client.addons.get("dummy")
        assert info.to_dict()["status"] == "loaded"
        assert '"id": "dummy"' in info.to_json()


class TestBadAddons:
    def test_an_incompatible_addon_is_listed_and_not_run(self, folder, client):
        module = AddonFactory.install(folder, api=', api_min="9.0", api_max="9.9"')
        info = client.addons.get("dummy")
        assert info.status is AddonStatus.INCOMPATIBLE
        assert "9.0" in info.detail
        client.sources.list()
        assert sys.modules[module].EVENTS == []

    def test_a_mismatched_entry_point_name_fails(self, folder, client):
        AddonFactory.install(folder, entry_name="other")
        assert client.addons.get("other").status is AddonStatus.FAILED

    def test_an_addon_that_cannot_be_imported_fails_without_breaking_vethuq(self, folder, client):
        AddonFactory.install(folder, target="vethuq_addon_dummy:Missing")
        assert client.addons.get("dummy").status is AddonStatus.FAILED
        assert client.sources.list() == []


class TestSettings:
    def test_roundtrip_is_namespaced(self, client):
        settings = client.addons.settings("backup")
        assert isinstance(settings, AddonSettings)
        client.sources.list()
        assert settings.get("mode", "default") == "default"
        settings.set("mode", "auto")
        assert settings.get("mode") == "auto"
        assert client.addons.settings("other").get("mode") is None
        settings.reset("mode")
        assert settings.get("mode") is None

    def test_setting_a_value_creates_the_database_if_needed(self, tmp_path):
        with vethuq.VethuQ(tmp_path / "fresh" / "vethuq.db") as fresh:
            assert fresh.addons.settings("backup").get("licence") is None
            fresh.addons.settings("backup").set("licence", "token")
            assert fresh.addons.settings("backup").get("licence") == "token"
            fresh.addons.settings("backup").reset("licence")
            assert fresh.addons.settings("backup").get("licence") is None

    def test_a_setting_is_stored_in_the_settings_table(self, client):
        client.sources.list()
        client.addons.settings("backup").set("mode", "auto")
        import sqlite3

        with sqlite3.connect(client.db_path) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='addon.backup.mode'").fetchone()
        assert row == ("auto",)

    @pytest.mark.parametrize("key", ["", "Mode", "a-b", "1a", "x" * 70])
    def test_bad_names_are_refused(self, client, key):
        with pytest.raises(vethuq.errors.InvalidSettingValueError):
            client.addons.settings("backup").set(key, "v")
