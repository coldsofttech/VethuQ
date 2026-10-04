import pytest
from vethuq_core.ocr.catalog import OcrCatalog
from vethuq_core.ocr.detection import LanguageDetector
from vethuq_core.readers import PageResult

EN = OcrCatalog.language("en")
TE = OcrCatalog.language("te")


def _page(text, confidence, source="ocr", lines=()):
    return PageResult(text=text, confidence=confidence, source=source, lines=tuple(lines))


class TestAssess:
    def test_a_confident_read_in_its_own_script_is_confident(self):
        result = LanguageDetector.assess([_page("The quick brown fox jumps", 0.93)], EN)

        assert result.verdict == LanguageDetector.CONFIDENT
        assert result.confidence == pytest.approx(0.93)
        assert result.script_share == 1.0

    def test_a_low_confidence_read_is_unsure(self):
        result = LanguageDetector.assess([_page("qzxv wplk mnbvc lkjh", 0.35)], EN)

        assert result.verdict == LanguageDetector.UNSURE

    def test_text_in_the_wrong_script_is_unsure_however_confident(self):
        result = LanguageDetector.assess([_page("తెలుగు పాఠం అమ్మ ఇల్లు", 0.95)], EN)

        assert result.verdict == LanguageDetector.UNSURE
        assert result.script_share == 0.0

    def test_telugu_read_in_telugu_is_confident(self):
        result = LanguageDetector.assess([_page("తెలుగు పాఠం అమ్మ ఇల్లు", 0.9)], TE)

        assert result.verdict == LanguageDetector.CONFIDENT

    def test_too_little_text_is_empty_not_unsure(self):
        assert LanguageDetector.assess([_page("ab", 0.2)], EN).verdict == LanguageDetector.EMPTY
        assert LanguageDetector.assess([_page("", 0.0)], EN).verdict == LanguageDetector.EMPTY

    def test_a_file_with_no_scanned_pages_is_native(self):
        pages = [_page("Native text layer here", 1.0, source="native")]

        assert LanguageDetector.assess(pages, EN).verdict == LanguageDetector.NATIVE

    def test_mixed_pages_are_not_scanned_pages(self):
        pages = [_page("Native and image text", 0.4, source="mixed")]

        assert LanguageDetector.assess(pages, EN).verdict == LanguageDetector.NATIVE

    def test_confidence_is_weighted_by_how_much_each_page_has(self):
        long_good = _page("a" * 90, 0.95)
        short_bad = _page("b" * 10, 0.10)

        result = LanguageDetector.assess([long_good, short_bad], EN)

        assert result.confidence == pytest.approx(0.865)
        assert result.verdict == LanguageDetector.CONFIDENT

    def test_the_thresholds_are_the_boundaries(self):
        at = LanguageDetector.MIN_CONFIDENCE
        text = "a" * LanguageDetector.MIN_LETTERS

        assert LanguageDetector.assess([_page(text, at)], EN).verdict == "confident"
        assert LanguageDetector.assess([_page(text, at - 0.01)], EN).verdict == "unsure"


class TestKeepLine:
    def test_a_confident_line_in_its_script_is_kept(self):
        assert LanguageDetector.keep_line("Invoice total", 0.9, EN)
        assert LanguageDetector.keep_line("తెలుగు పాఠం", 0.9, TE)

    def test_a_low_confidence_line_is_dropped(self):
        assert not LanguageDetector.keep_line("Invoice total", 0.3, EN)

    def test_a_line_in_another_script_is_dropped(self):
        assert not LanguageDetector.keep_line("తెలుగు పాఠం", 0.95, EN)
        assert not LanguageDetector.keep_line("Invoice total", 0.95, TE)

    def test_a_line_that_is_mostly_numbers_needs_a_confident_read(self):
        assert LanguageDetector.keep_line("2024-001 / 15.50", 0.9, EN)
        assert not LanguageDetector.keep_line("2024-001 / 15.50", 0.7, EN)

    def test_a_mostly_own_script_line_with_a_little_other_script_is_kept(self):
        assert LanguageDetector.keep_line("తెలుగు పాఠం abc", 0.9, TE)


class TestFilterPages:
    def test_unbelievable_lines_are_dropped_and_confidence_recomputed(self):
        lines = [("Invoice total", 0.95), ("qzxv", 0.2), ("Museum", 0.85)]
        page = _page("Invoice total\nqzxv\nMuseum", 0.667, lines=lines)

        [filtered] = LanguageDetector.filter_pages([page], EN)

        assert filtered.text == "Invoice total\nMuseum"
        assert filtered.confidence == pytest.approx(0.90)
        assert filtered.lines == (("Invoice total", 0.95), ("Museum", 0.85))

    def test_a_page_where_nothing_is_believable_becomes_empty(self):
        page = _page("qzxv", 0.2, lines=[("qzxv", 0.2)])

        [filtered] = LanguageDetector.filter_pages([page], EN)

        assert filtered.text == "" and filtered.confidence == 0.0

    def test_native_mixed_and_line_less_pages_are_left_alone(self):
        pages = [
            _page("native text", 1.0, source="native"),
            _page("mixed text", 0.5, source="mixed", lines=[("mixed text", 0.5)]),
            _page("no lines", 0.4),
        ]

        assert LanguageDetector.filter_pages(pages, EN) == pages


class TestLanguagesInText:
    def test_finds_the_candidates_whose_script_is_present(self):
        assert LanguageDetector.languages_in_text("hello తెలుగు", [EN, TE]) == ["en", "te"]
        assert LanguageDetector.languages_in_text("hello", [EN, TE]) == ["en"]
        assert LanguageDetector.languages_in_text("తెలుగు", [EN, TE]) == ["te"]
        assert LanguageDetector.languages_in_text("123", [EN, TE]) == []
