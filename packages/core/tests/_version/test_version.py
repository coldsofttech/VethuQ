from __future__ import annotations

import platform
from importlib import metadata

import pytest

from vethuq._db import _Schema
from vethuq._version import _Version


class TestVersion:
    def test_app_version_is_the_installed_one(self, monkeypatch):
        monkeypatch.setattr(metadata, "version", lambda name: "9.8.7")

        assert _Version.app_version() == "9.8.7"

    def test_app_version_looks_up_the_vethuq_distribution(self, monkeypatch):
        seen = []
        monkeypatch.setattr(metadata, "version", lambda name: seen.append(name) or "1.0.0")

        _Version.app_version()

        assert seen == ["VethuQ"]

    def test_app_version_falls_back_when_not_installed(self, monkeypatch):
        def missing(name):
            raise metadata.PackageNotFoundError(name)

        monkeypatch.setattr(metadata, "version", missing)

        assert _Version.app_version() == "0.1.0"
        assert _Version.FALLBACK == "0.1.0"

    def test_python_and_platform(self):
        assert _Version.python_version() == platform.python_version()
        assert _Version.platform_name() == platform.platform()

    def test_db_schema_is_the_current_schema_version(self, monkeypatch):
        assert _Version.db_schema() == _Schema.VERSION
        monkeypatch.setattr(_Schema, "VERSION", 7)
        assert _Version.db_schema() == 7

    @pytest.mark.parametrize(
        "kind",
        ["file_types", "search_engines", "ocr_engines", "ocr_languages", "add_ons"],
    )
    def test_without_a_manager_the_lists_are_empty(self, kind):
        assert getattr(_Version, kind)() == ()


class TestInstalledLists:
    class Spec:
        def __init__(self, id):
            self.id = id

    class Item:
        def __init__(self, id, running=True):
            self.id = id
            self.addon = object() if running else None

    class Manager:
        def __init__(self, items):
            self._items = items

        def loaded(self):
            return {item.id: item for item in self._items}

        def file_type_specs(self):
            return [TestInstalledLists.Spec(i) for i in ("pdf", "csv")]

        def search_engine_specs(self):
            return [TestInstalledLists.Spec(i) for i in ("like", "exact")]

        def ocr_engine_providers(self):
            return [TestInstalledLists.Spec("paddle")]

        def language_specs(self):
            return [TestInstalledLists.Spec("en")]

    @pytest.fixture
    def manager(self):
        item = TestInstalledLists.Item
        return self.Manager([item("pdf"), item("broken", running=False), item("english")])

    def test_each_kind_lists_the_ids_sorted(self, manager):
        assert _Version.file_types(manager) == ("csv", "pdf")
        assert _Version.search_engines(manager) == ("exact", "like")
        assert _Version.ocr_engines(manager) == ("paddle",)
        assert _Version.ocr_languages(manager) == ("en",)

    def test_add_ons_are_the_running_ones(self, manager):
        assert _Version.add_ons(manager) == ("english", "pdf")

class TestBundles:
    def test_none_installed(self, monkeypatch):
        monkeypatch.setattr(metadata, "entry_points", lambda group: [])
        assert _Version.bundles() == ()

    def test_the_installed_bundles_by_name(self, monkeypatch):
        class Point:
            def __init__(self, name):
                self.name = name

        seen = []

        def entry_points(group):
            seen.append(group)
            return [Point("image"), Point("archives"), Point("image")]

        monkeypatch.setattr(metadata, "entry_points", entry_points)
        assert _Version.bundles() == ("archives", "image")
        assert seen == ["vethuq.bundles"]
