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
        "placeholder",
        [
            "file_types",
            "search_engines",
            "ocr_engines",
            "ocr_languages",
            "add_ons",
            "bundles",
        ],
    )
    def test_placeholders_are_empty_for_now(self, placeholder):
        assert getattr(_Version, placeholder)() == ()
