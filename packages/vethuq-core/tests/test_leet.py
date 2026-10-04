import pytest
from vethuq_core.leet import Leet
from vethuq_core.settings import SearchSettings


class TestClasses:
    def test_basic_classes(self):
        classes = Leet.classes("basic")

        assert {classes[c] for c in "a4@"} == {"a"}
        assert {classes[c] for c in "e3"} == {"e"}
        assert {classes[c] for c in "il1"} == {"i"}  # 1 can be either, so they share a class
        assert {classes[c] for c in "o0"} == {"o"}
        assert {classes[c] for c in "s5$"} == {"s"}
        assert {classes[c] for c in "t7"} == {"t"}
        assert "8" not in classes and "!" not in classes and "(" not in classes

    def test_each_level_adds_to_the_one_before(self):
        basic, standard, extended = (
            Leet.classes(level) for level in SearchSettings.LEETSPEAK_LEVELS
        )

        assert set(basic) < set(standard) < set(extended)
        assert standard["8"] == "b" and standard["9"] == "g" and standard["2"] == "z"
        assert {standard[c] for c in "il1!|"} == {"i"}
        assert "(" not in standard and extended["("] == "c" and extended["{"] == "c"

    def test_multi_character_spellings_are_left_out(self):
        assert not any(len(char) > 1 for char in Leet.classes("extended"))
        assert "|" in Leet.classes("extended")  # but its single-character ones stay

    def test_levels_match_the_settings(self):
        from vethuq_core.leet import LEVEL_TABLES

        assert tuple(LEVEL_TABLES) == SearchSettings.LEETSPEAK_LEVELS


class TestNoise:
    def test_symbols_that_can_be_look_alikes_are_not_noise(self):
        assert Leet.symbols() == frozenset("@$!|+([{")
        for char in "@$!|+([{":
            assert not Leet.is_noise(char)

    @pytest.mark.parametrize("char", [" ", "\t", ".", ",", "-", "_", "#", "%", "&", "*", "/", "\\"])
    def test_other_punctuation_and_whitespace_is_noise(self, char):
        assert Leet.is_noise(char)

    @pytest.mark.parametrize("char", ["a", "Z", "7", "0", "é", "ß", "日"])
    def test_letters_and_digits_never_are(self, char):
        assert not Leet.is_noise(char)


class TestFold:
    def test_folds_to_the_class_letter_ignoring_case(self):
        assert [Leet.fold(c, "basic", False) for c in "3E@A4lL1"] == list("eeaaaiii")
        assert Leet.fold("H", "basic", False) == "h"

    def test_a_symbol_outside_the_level_stays_itself(self):
        assert Leet.fold("!", "basic", False) == "!"
        assert Leet.fold("!", "standard", False) == "i"
        assert Leet.fold("8", "basic", False) == "8"
        assert Leet.fold("8", "standard", False) == "b"

    def test_case_sensitive_keeps_the_case_of_letters(self):
        assert Leet.fold("E", "basic", True) == "E"
        assert Leet.fold("e", "basic", True) == "e"
        assert Leet.fold("L", "basic", True) == "I"
        assert Leet.fold("3", "basic", True) == "e"  # a look-alike is the lower-case letter
        assert Leet.fold("H", "basic", True) == "H"


class TestSkeleton:
    @pytest.mark.parametrize(
        ("text", "skeleton"),
        [
            ("hello", "heiio"),
            ("h3ll0", "heiio"),
            ("h..e llo", "heiio"),
            ("h @ e # l l o", "haeiio"),  # @ is read as an a, not skipped
            ("p@55w0rd", "password"),
            ("HELLO World!", "heiioworidi"),
            ("", ""),
            ("  ...  ", ""),
            ("2024-01-31", "zozaoiei"),
        ],
    )
    def test_skeleton(self, text, skeleton):
        assert Leet.skeleton(text) == skeleton

    def test_digits_all_fold_to_letters(self):
        assert Leet.skeleton("0123456789") == "oizeasgtbg"

    def test_is_the_same_for_every_spelling_of_a_word(self):
        spellings = ["hello", "HELLO", "h3ll0", "h e l l o", "h.e.l.l.o", "he11o", "h-3-1-1-0"]

        assert len({Leet.skeleton(text) for text in spellings}) == 1
