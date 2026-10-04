from importlib import metadata

from vethuq_core.ocr.catalog import OcrCatalog, OcrComponentInfo
from vethuq_core.version import VersionInfo


def _info(**overrides) -> OcrComponentInfo:
    data = {"id": "x", "label": "X", "extra": "ocr-x", "requires": [], "modules": []}
    data.update(overrides)
    return OcrComponentInfo.from_manifest(data)


class TestOcrComponentInfo:
    def test_from_manifest_defaults(self):
        info = _info()

        assert info.requires == ()
        assert info.modules == ()
        assert info.default is False

    def test_installed_without_modules_or_requirements(self):
        assert _info().is_installed()

    def test_missing_module_is_not_installed(self):
        assert not _info(modules=["vethuq_no_such_module"]).is_installed()

    def test_present_module_is_installed(self):
        assert _info(modules=["json"]).is_installed()

    def test_missing_requirement_is_not_installed(self):
        assert not _info(requires=["vethuq-no-such-dist>=1.0"]).is_installed()

    def test_present_requirement_with_specifier_is_installed(self, monkeypatch):
        monkeypatch.setattr(metadata, "version", lambda name: "3.1" if name == "paddleocr" else "")

        assert _info(requires=["paddleocr>=3.0"]).is_installed()


class TestOcrCatalog:
    def test_engines_are_loaded_from_manifests_default_first(self):
        engines = OcrCatalog.engines()

        assert "paddle" in [e.id for e in engines]
        assert engines[0].default

    def test_languages_include_default_english(self):
        languages = OcrCatalog.languages()

        assert languages[0].id == "en"
        assert languages[0].label == "English"

    def test_installed_languages_include_english(self):
        assert "en" in [lang.id for lang in OcrCatalog.installed_languages()]

    def test_installed_engines_drop_uninstalled(self, monkeypatch):
        monkeypatch.setattr(OcrComponentInfo, "is_installed", lambda self: False)

        assert OcrCatalog.installed_engines() == []


class TestVersionInfoOcr:
    def test_rows_list_ocr_engines_and_languages(self, monkeypatch):
        monkeypatch.setattr(OcrComponentInfo, "is_installed", lambda self: True)
        rows = dict(VersionInfo.rows())

        assert "PaddleOCR" in rows["OCR engines"]
        assert "English" in rows["Languages"]

    def test_rows_show_none_when_nothing_installed(self, monkeypatch):
        monkeypatch.setattr(OcrComponentInfo, "is_installed", lambda self: False)
        rows = dict(VersionInfo.rows())

        assert rows["OCR engines"] == "none"
        assert rows["Languages"] == "none"
