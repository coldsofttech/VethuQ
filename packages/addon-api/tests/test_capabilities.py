from __future__ import annotations

from pathlib import Path

import pytest

from vethuq_addon_api import (
    Addon,
    CorruptedFileError,
    DocumentReader,
    FileRemovedError,
    FileTypeSpec,
    LanguageSpec,
    Manifest,
    OcrEngine,
    OcrEngineProvider,
    OcrModelSpec,
    OcrPhaseSpec,
    OcrResult,
    PasswordProtectedError,
    ReadPage,
    UnreadableFileError,
    extended_path,
)
from vethuq_addon_api.testing import FakeEngine, FakeHost, FakeReader


class TestReaders:
    def test_the_errors_are_unreadable_file_errors_with_the_path(self):
        for error in (
            FileRemovedError("a.pdf"),
            PasswordProtectedError("a.pdf"),
            CorruptedFileError("a.pdf", "bad xref"),
        ):
            assert isinstance(error, UnreadableFileError)
            assert error.path == Path("a.pdf")
        assert "password" in str(PasswordProtectedError("a.pdf"))
        assert "bad xref" in str(CorruptedFileError("a.pdf", "bad xref"))
        assert "no longer exists" in str(FileRemovedError("a.pdf"))

    def test_a_reader_must_implement_read(self):
        with pytest.raises(TypeError):
            DocumentReader()  # type: ignore[abstract]

    def test_the_fake_reader_yields_its_pages(self):
        pages = [ReadPage("one", (), lambda region: "img1"), ReadPage("two", (), lambda r: "img2")]
        reader = FakeReader(pages)
        assert [p.native_text for p in reader.read(Path("x.pdf"))] == ["one", "two"]
        assert [p.native_text for p in reader.read(Path("x.pdf"), page_number=2)] == ["two"]
        assert reader.opened == [Path("x.pdf"), Path("x.pdf")]
        assert reader.processing_weight == 1.0

    def test_extended_path_is_unchanged_off_windows(self, tmp_path):
        assert extended_path(tmp_path / "a.pdf") == tmp_path / "a.pdf"

    def test_extended_path_on_windows(self, monkeypatch):
        monkeypatch.setattr("vethuq_addon_api.readers.sys.platform", "win32")
        monkeypatch.setattr("vethuq_addon_api.readers.os.path.abspath", lambda p: "C:\\docs\\a.pdf")
        assert str(extended_path("a.pdf")) == "\\\\?\\C:\\docs\\a.pdf"
        assert extended_path("\\\\?\\C:\\x") == Path("\\\\?\\C:\\x")


class TestEngines:
    def test_the_fake_engine_is_an_engine(self):
        engine = FakeEngine({"img": "hello\nworld"}, language="en")
        assert isinstance(engine.recognize("img"), OcrResult)
        assert engine.recognize("img").text == "hello\nworld"
        assert engine.recognize("other").text == ""
        assert engine.recognize("other").confidence == 0.0
        assert engine.calls == ["img", "img", "other", "other"]
        assert (engine.name, engine.language) == ("fake-ocr 1.0", "en")
        assert engine.recognize("img").lines == (("hello", 0.9), ("world", 0.9))

    def test_a_provider_must_implement_its_methods(self):
        with pytest.raises(TypeError):
            OcrEngineProvider()  # type: ignore[abstract]

    def test_a_provider_defaults(self):
        class Provider(OcrEngineProvider):
            id = "p"
            label = "P"
            profiles = ("mobile",)

            def create(self, language, profile, models_dir, use_gpu=False) -> OcrEngine:
                return FakeEngine()

            def required_models(self, language, profile):
                return [OcrModelSpec("m", "recognition")]

            def known_models(self, languages):
                return []

            def model_path(self, models_dir, name):
                return models_dir / name

            def download(self, models_dir, names, on_progress=None):
                return {}

        provider = Provider()
        assert provider.available and provider.reason == ""
        assert provider.required_models(LanguageSpec("en", "English"), "mobile")[0].shared is False


class TestSpecs:
    def test_phase_defaults(self):
        phase = OcrPhaseSpec("quick", "Quick", 1, profile="mobile")
        assert (phase.angles, phase.available, phase.reason) == ((0,), True, "")

    def test_file_type_spec(self):
        spec = FileTypeSpec("pdf", "PDF", (".pdf",), FakeReader())
        assert spec.available and spec.extensions == (".pdf",)

    def test_an_addon_provides_nothing_by_default(self, tmp_path):
        class Plain(Addon):
            manifest = Manifest("plain", "Plain", "1.0.0")

        addon = Plain(FakeHost(tmp_path / "v.db"))
        assert (addon.file_types(), addon.ocr_engines(), addon.ocr_phases()) == ([], [], [])
