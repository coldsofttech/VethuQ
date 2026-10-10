from __future__ import annotations

import re

import core


class TestPublicApi:
    def test_app_name_and_tagline_come_from_the_brand(self):
        assert core.APP_NAME == "VethuQ"
        assert core.APP_TAGLINE == "Document intelligence and evidence infrastructure."

    def test_app_version_is_a_version_string_and_matches_dunder_version(self):
        assert re.match(r"^\d+\.\d+\.\d+", core.APP_VERSION)
        assert core.__version__ == core.APP_VERSION

    def test_only_the_public_names_are_exported(self):
        assert core.__all__ == ["APP_NAME", "APP_TAGLINE", "APP_VERSION", "__version__"]
        assert not any("alette" in name or "rand" in name for name in core.__all__)

    def test_version_falls_back_when_the_package_is_not_installed(self, monkeypatch):
        import importlib
        import importlib.metadata as metadata

        def missing(_name):
            raise metadata.PackageNotFoundError

        monkeypatch.setattr(metadata, "version", missing)
        try:
            reloaded = importlib.reload(core)
            assert reloaded.APP_VERSION == "0.1.0"
        finally:
            monkeypatch.undo()
            importlib.reload(core)
