import pytest
from vethuq_core.languages import Scripts

TELUGU_WORD = "తెలుగు"
TELUGU_SYLLABLE = "కాకి"
CONJUNCT = "క్ష"


class TestContains:
    def test_telugu_text_is_telugu(self):
        assert Scripts.contains(TELUGU_WORD, Scripts.TELUGU)

    def test_vowel_sign_and_virama_alone_count(self):
        assert Scripts.contains("ా", Scripts.TELUGU)
        assert Scripts.contains("్", Scripts.TELUGU)

    def test_english_is_not_telugu(self):
        assert not Scripts.contains("invoice total", Scripts.TELUGU)

    def test_english_is_latin(self):
        assert Scripts.contains("invoice", Scripts.LATIN)

    def test_accented_latin_is_latin(self):
        assert Scripts.contains("é", Scripts.LATIN)

    def test_digits_and_punctuation_are_no_script(self):
        assert not Scripts.contains("2024-001, $1.50", Scripts.LATIN)
        assert not Scripts.contains("2024-001, $1.50", Scripts.TELUGU)

    def test_unknown_script_is_false(self):
        assert not Scripts.contains("abc", "klingon")

    def test_range_edges(self):
        assert Scripts.contains("ఀ", Scripts.TELUGU)
        assert Scripts.contains("౿", Scripts.TELUGU)
        assert not Scripts.contains("௿", Scripts.TELUGU)
        assert not Scripts.contains("ಀ", Scripts.TELUGU)


class TestPresentAndDominant:
    def test_mixed_text_has_both(self):
        assert Scripts.present(f"invoice {TELUGU_WORD}") == {Scripts.LATIN, Scripts.TELUGU}

    def test_counts_characters_per_script(self):
        counts = Scripts.counts(f"ab {TELUGU_SYLLABLE}")

        assert counts[Scripts.LATIN] == 2
        assert counts[Scripts.TELUGU] == len(TELUGU_SYLLABLE)

    def test_dominant_is_the_larger_script(self):
        assert Scripts.dominant(f"a {TELUGU_WORD}") == Scripts.TELUGU
        assert Scripts.dominant(f"{TELUGU_SYLLABLE} abcdefgh") == Scripts.LATIN

    def test_dominant_of_no_script_is_none(self):
        assert Scripts.dominant("1234 --") is None
        assert Scripts.dominant("") is None


class TestStripsMarks:
    @pytest.mark.parametrize("char", ["e", "E", "é", "ü"])
    def test_latin_marks_may_be_stripped(self, char):
        assert Scripts.strips_marks(char)

    @pytest.mark.parametrize("char", ["క", "ా", "్", "ల"])
    def test_telugu_marks_are_part_of_the_syllable(self, char):
        assert not Scripts.strips_marks(char)

    @pytest.mark.parametrize("char", ["日", "1", " ", "я"])
    def test_other_text_keeps_the_existing_behaviour(self, char):
        assert Scripts.strips_marks(char)
