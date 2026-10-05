import json

import pytest
from vethuq_core.languages import Languages
from vethuq_core.ocr.catalog import OcrCatalog, OcrComponentInfo
from vethuq_core.paths import Paths


@pytest.fixture
def selection_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(Paths, "platform_data_root", staticmethod(lambda: tmp_path / "platform"))
    return tmp_path


def _write(folder, data):
    (folder / OcrCatalog.LANGUAGE_SELECTION_FILENAME).write_text(json.dumps(data), encoding="utf-8")


class TestManifests:
    def test_english_is_the_default_and_first(self):
        assert OcrCatalog.default_language().id == "en"
        assert OcrCatalog.languages()[0].id == "en"
        assert [lang.id for lang in OcrCatalog.languages() if lang.default] == ["en"]

    def test_english_declares_its_script_and_model_code(self):
        english = OcrCatalog.language("en")

        assert english.script == "latin"
        assert english.paddle_lang == "en"

    def test_telugu_declares_its_script_model_code_and_extra(self):
        telugu = OcrCatalog.language("te")

        assert telugu.label == "Telugu"
        assert telugu.native_label == "తెలుగు"
        assert telugu.display_label == "Telugu (తెలుగు)"
        assert telugu.script == "telugu"
        assert telugu.paddle_lang == "te"
        assert telugu.extra == "lang-te"
        assert telugu.install_hint == "pip install vethuq[lang-te]"
        assert not telugu.default

    def test_a_language_without_a_native_name_shows_its_label(self):
        assert OcrCatalog.language("en").display_label == "English"

    def test_the_installer_labels_stay_ascii(self):
        assert all(lang.label.isascii() for lang in OcrCatalog.languages())

    def test_unknown_language_is_none(self):
        assert OcrCatalog.language("xx") is None

    def test_every_language_script_is_a_known_script(self):
        from vethuq_core.languages import Scripts

        assert all(Scripts.get(lang.script) for lang in OcrCatalog.languages())


class TestInstalled:
    def test_telugu_needs_its_marker_package(self, monkeypatch):
        monkeypatch.setattr(
            OcrComponentInfo,
            "is_installed",
            lambda self: not self.modules or self.modules != ("vethuq_lang_te",),
        )

        assert [lang.id for lang in OcrCatalog.installed_languages()] == ["en"]

    def test_marker_package_is_installed_in_the_dev_environment(self):
        assert "te" in [lang.id for lang in OcrCatalog.installed_languages()]


class TestSelection:
    def test_everything_installed_is_enabled_without_a_selection(self, selection_dir):
        assert OcrCatalog.language_selection() is None
        assert Languages.enabled_ids() == ["en", "te"]

    def test_selection_limits_languages_but_never_english(self, selection_dir):
        _write(selection_dir, {"enabled": ["te"]})

        assert Languages.enabled_ids() == ["en", "te"]
        _write(selection_dir, {"enabled": []})
        assert Languages.enabled_ids() == ["en"]

    def test_english_only_selection(self, selection_dir):
        _write(selection_dir, {"enabled": ["en"]})

        assert Languages.enabled_ids() == ["en"]

    def test_older_installer_single_choice_still_reads(self, selection_dir):
        _write(selection_dir, {"language": "en"})

        assert OcrCatalog.language_selection() == {"en"}
        assert Languages.enabled_ids() == ["en"]

    def test_unreadable_selection_is_ignored(self, selection_dir):
        (selection_dir / OcrCatalog.LANGUAGE_SELECTION_FILENAME).write_text("not json")

        assert OcrCatalog.language_selection() is None
        assert Languages.enabled_ids() == ["en", "te"]

    def test_not_installed_is_never_enabled(self, selection_dir, monkeypatch):
        _write(selection_dir, {"enabled": ["te"]})
        monkeypatch.setattr(OcrComponentInfo, "is_installed", lambda self: self.id == "en")

        assert Languages.enabled_ids() == ["en"]


class TestForText:
    def test_english_text_calls_for_english_only(self, selection_dir):
        assert [lang.id for lang in Languages.for_text("invoice total")] == ["en"]

    def test_telugu_text_calls_for_telugu(self, selection_dir):
        assert [lang.id for lang in Languages.for_text("తెలుగు")] == ["te"]

    def test_mixed_text_calls_for_both_in_catalog_order(self, selection_dir):
        assert [lang.id for lang in Languages.for_text("invoice తెలుగు")] == ["en", "te"]

    def test_digits_only_call_for_nothing(self, selection_dir):
        assert Languages.for_text("2024-001") == []

    def test_a_language_that_is_not_enabled_is_not_called_for(self, selection_dir):
        _write(selection_dir, {"enabled": ["en"]})

        assert Languages.for_text("తెలుగు") == []

    def test_default_only_text(self):
        assert Languages.is_default_only("invoice 2024")
        assert Languages.is_default_only("")
        assert not Languages.is_default_only("invoice తెలుగు")


def test_the_languages_package_imports_first_in_a_fresh_interpreter():
    import subprocess
    import sys

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "from vethuq_core.languages import Languages, LanguageSelection"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
