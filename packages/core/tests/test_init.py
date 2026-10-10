from __future__ import annotations

import re

import vethuq


class TestPublicApi:
    def test_app_name_and_tagline_come_from_the_brand(self):
        assert vethuq.APP_NAME == "VethuQ"
        assert vethuq.APP_TAGLINE == "Document intelligence and evidence infrastructure."

    def test_app_version_is_a_version_string_and_matches_dunder_version(self):
        assert re.match(r"^\d+\.\d+\.\d+", vethuq.APP_VERSION)
        assert vethuq.__version__ == vethuq.APP_VERSION

    def test_only_the_public_names_are_exported(self):
        assert vethuq.__all__ == [
            "APP_NAME",
            "APP_TAGLINE",
            "APP_VERSION",
            "__version__",
            "errors",
            "paths",
            "Paths",
            "Language",
            "PurgeResult",
            "SortOrder",
            "Source",
            "SourceSortBy",
            "SourceStatus",
            "SourceType",
            "VethuQ",
        ]
        assert not any("alette" in name or "rand" in name for name in vethuq.__all__)

    def test_paths_class_is_importable_from_the_package(self):
        from vethuq import Paths

        assert Paths is vethuq.paths.Paths
        assert Paths.DB_NAME == "vethuq.db"

    def test_version_falls_back_when_the_package_is_not_installed(self, monkeypatch):
        import importlib
        import importlib.metadata as metadata

        def missing(_name):
            raise metadata.PackageNotFoundError

        monkeypatch.setattr(metadata, "version", missing)
        try:
            reloaded = importlib.reload(vethuq)
            assert reloaded.APP_VERSION == "0.1.0"
        finally:
            monkeypatch.undo()
            importlib.reload(vethuq)
