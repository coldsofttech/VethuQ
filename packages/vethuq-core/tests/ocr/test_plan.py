import json

import pytest
from vethuq_core.errors import LanguageUnavailableError
from vethuq_core.languages import Candidates, UnknownLanguageError
from vethuq_core.ocr.plan import LanguagePlan
from vethuq_core.paths import Paths
from vethuq_core.readers import PageResult
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Sources

JUNK = [("qzxv wplk", 0.31), ("mnbvc lkjh", 0.27)]


def _scanned(text, confidence, lines=()):
    return PageResult(text, confidence, "ocr", lines=tuple(lines))


class TestCandidates:
    def test_the_default_is_auto_which_is_every_enabled_language(self, storage):
        assert LanguagePlan.candidates(storage) == Candidates(("en", "te"), explicit=False)

    def test_english_alone_when_that_is_all_that_is_enabled(self, storage):
        (Paths.default_data_root() / "languages.json").write_text(
            json.dumps({"enabled": ["en"]}), encoding="utf-8"
        )

        candidates = LanguagePlan.candidates(storage)

        assert candidates == Candidates(("en",), explicit=False)
        assert not candidates.needs_detection

    def test_the_setting_is_not_explicit(self, storage):
        OcrSettings.set_languages(storage, "te")

        assert LanguagePlan.candidates(storage) == Candidates(("te",), explicit=False)

    def test_a_source_beats_the_setting_and_is_explicit(self, storage, tmp_path):
        OcrSettings.set_languages(storage, "en")
        source = Sources.add(storage, tmp_path, languages="te")

        assert LanguagePlan.candidates(storage, source) == Candidates(("te",), explicit=True)

    def test_a_flag_beats_the_source(self, storage, tmp_path):
        source = Sources.add(storage, tmp_path, languages="te")

        assert LanguagePlan.candidates(storage, source, "en") == Candidates(("en",), True)

    def test_a_source_without_languages_falls_through_to_the_setting(self, storage, tmp_path):
        OcrSettings.set_languages(storage, "te")
        source = Sources.add(storage, tmp_path)

        assert LanguagePlan.candidates(storage, source).ids == ("te",)

    def test_auto_on_a_source(self, storage, tmp_path):
        OcrSettings.set_languages(storage, "te")
        source = Sources.add(storage, tmp_path, languages="auto")

        assert LanguagePlan.candidates(storage, source) == Candidates(("en", "te"), True)

    def test_an_unavailable_language_is_refused(self, storage):
        (Paths.default_data_root() / "languages.json").write_text(
            json.dumps({"enabled": ["en"]}), encoding="utf-8"
        )

        with pytest.raises(LanguageUnavailableError):
            LanguagePlan.candidates(storage, override="te")

    def test_an_unknown_language_is_refused(self, storage):
        with pytest.raises(UnknownLanguageError):
            LanguagePlan.candidates(storage, override="xx")


class TestAfterFirstPass:
    def test_a_single_language_is_just_recorded(self):
        pages = [_scanned("anything at all here", 0.2)]

        result = LanguagePlan.after_first_pass(Candidates(("te",), explicit=True), pages)

        assert result.pages == pages
        assert result.rows == [("te", 0, "done", "manual", pytest.approx(0.2))]

    def test_the_default_setting_records_default(self):
        result = LanguagePlan.after_first_pass(
            Candidates(("en",), explicit=False), [_scanned("some words in here", 0.9)]
        )

        assert result.rows[0][3] == "default"

    def test_a_confident_first_language_skips_the_rest(self):
        pages = [_scanned("The invoice total is due", 0.95)]

        result = LanguagePlan.after_first_pass(Candidates(("en", "te")), pages)

        assert result.pages == pages
        assert result.rows == [
            ("en", 0, "done", "auto", pytest.approx(0.95)),
            ("te", 1, "skipped", "auto", None),
        ]

    def test_an_unsure_first_language_queues_the_rest_and_drops_its_made_up_lines(self):
        page = _scanned("qzxv wplk\nmnbvc lkjh", 0.29, lines=JUNK)

        result = LanguagePlan.after_first_pass(Candidates(("en", "te")), [page])

        assert result.rows == [
            ("en", 0, "done", "auto", pytest.approx(0.29)),
            ("te", 1, "pending", "auto", None),
        ]
        assert result.pages[0].text == ""

    def test_the_rest_are_queued_in_order(self):
        page = _scanned("qzxv wplk\nmnbvc lkjh", 0.29, lines=JUNK)

        result = LanguagePlan.after_first_pass(Candidates(("en", "te", "xx")), [page])

        assert [(r[0], r[1], r[2]) for r in result.rows] == [
            ("en", 0, "done"),
            ("te", 1, "pending"),
            ("xx", 2, "pending"),
        ]

    def test_nothing_read_is_not_a_reason_to_try_the_others(self):
        result = LanguagePlan.after_first_pass(Candidates(("en", "te")), [_scanned("", 0.0)])

        assert [r[2] for r in result.rows] == ["done", "skipped"]

    def test_a_file_with_a_text_layer_shows_its_language_by_script(self):
        pages = [PageResult("తెలుగు పాఠం అమ్మ ఇల్లు", 1.0, "native")]

        result = LanguagePlan.after_first_pass(Candidates(("en", "te")), pages)

        assert [(r[0], r[2]) for r in result.rows] == [("en", "skipped"), ("te", "done")]
        assert result.pages == pages

    def test_a_text_layer_in_both_scripts_marks_both(self):
        pages = [PageResult("Invoice total తెలుగు", 1.0, "native")]

        result = LanguagePlan.after_first_pass(Candidates(("en", "te")), pages)

        assert [(r[0], r[2]) for r in result.rows] == [("en", "done"), ("te", "done")]
