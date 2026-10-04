import pytest
from vethuq_core.search.normalizers import (
    CaseNormalizer,
    Folded,
    LeetspeakNormalizer,
    Normalizers,
    UnicodeNormalizer,
)


class TestFolded:
    def test_without_a_map_a_span_is_the_same_span(self):
        assert Folded("hello").original(1, 3) == (1, 3)

    def test_with_a_map_a_span_is_traced_back(self):
        folded = Folded("cafe", [0, 1, 2, 3], [1, 2, 3, 5])

        assert folded.original(3, 4) == (3, 5)
        assert folded.original(0, 4) == (0, 5)

    def test_an_empty_span_is_a_point(self):
        folded = Folded("ab", [0, 2], [1, 3])

        assert folded.original(1, 1) == (2, 2)
        assert folded.original(2, 2) == (2, 2)


class TestRegistry:
    def test_the_three_normalizers_are_registered_in_application_order(self):
        assert Normalizers.available() == ["unicode", "case", "leetspeak"]
        assert Normalizers.ORDER == ("unicode", "case", "leetspeak")

    def test_get(self):
        assert isinstance(Normalizers.get("case"), CaseNormalizer)
        assert isinstance(Normalizers.get("unicode"), UnicodeNormalizer)
        assert isinstance(Normalizers.get("leetspeak"), LeetspeakNormalizer)
        with pytest.raises(ValueError, match="Unknown normalizer"):
            Normalizers.get("stemming")

    def test_each_has_an_identity_level_among_its_levels(self):
        for name in Normalizers.available():
            normalizer = Normalizers.get(name)
            assert normalizer.identity in normalizer.levels
            assert normalizer.fold("Hello ÉÀ h3ll0", normalizer.identity).text == "Hello ÉÀ h3ll0"

    def test_a_custom_normalizer_can_be_registered(self):
        class Shout:
            name = "shout"
            levels = ("off", "on")
            identity = "off"

            def fold(self, text, level):
                return Folded(text.upper() if level == "on" else text)

            def char_table(self, level):
                return None

        Normalizers.register(Shout())
        try:
            assert Normalizers.available()[-1] == "shout"  # after the built-in ones
            assert Normalizers.pipeline({"shout": "on"}).fold("hi").text == "HI"
        finally:
            Normalizers._normalizers.pop("shout")


class TestPipeline:
    def test_applies_the_steps_in_order(self):
        pipeline = Normalizers.pipeline({"leetspeak": "basic", "case": "ignore"})

        assert pipeline.fold("H3LL0 @LL").text == "heiio aii"  # case first, then look-alikes
        assert pipeline.fold("H3LL0").starts is None  # nothing moved

    def test_case_match_keeps_the_case_of_letters(self):
        pipeline = Normalizers.pipeline({"case": "match", "leetspeak": "basic"})

        assert pipeline.fold("H3LL0").text == "HeIIo"

    def test_identity_levels_change_nothing(self):
        pipeline = Normalizers.pipeline({"case": "match", "leetspeak": "off", "unicode": "off"})

        assert pipeline.is_identity
        assert pipeline.fold("H3llo é").text == "H3llo é"

    def test_a_pipeline_is_not_the_identity_with_a_step_on(self):
        assert not Normalizers.pipeline({"case": "ignore"}).is_identity

    def test_rejects_an_unknown_normalizer_or_level(self):
        with pytest.raises(ValueError, match="Unknown normalizer"):
            Normalizers.pipeline({"stemming": "on"})
        with pytest.raises(ValueError, match="case must be one of match, ignore"):
            Normalizers.pipeline({"case": "sometimes"})

    def test_composes_the_maps_of_steps_that_move_positions(self):
        pipeline = Normalizers.pipeline({"unicode": "basic", "case": "ignore"})
        text = "Café BAR"  # an accent written as its own character

        folded = pipeline.fold(text)

        assert folded.text == "café bar"
        start = folded.text.index("bar")
        assert folded.original(start, start + 3) == (text.index("BAR"), len(text))
        assert text[slice(*folded.original(3, 4))] == "é"


class TestCaseNormalizer:
    def test_ignore_lower_cases_and_match_does_not(self):
        case = CaseNormalizer()

        assert case.fold("Hello WORLD", "ignore").text == "hello world"
        assert case.fold("Hello WORLD", "match").text == "Hello WORLD"

    def test_positions_never_move(self):
        folded = CaseNormalizer().fold("İstanbul ÉCOLE", "ignore")

        assert folded.starts is None
        assert len(folded.text) == len("İstanbul ÉCOLE")

    def test_has_no_character_table(self):
        assert CaseNormalizer().char_table("ignore") is None


class TestUnicodeNormalizer:
    unicode = UnicodeNormalizer()

    def test_settled_text_is_returned_as_it_is(self):
        folded = self.unicode.fold("plain text", "full")

        assert folded.text == "plain text" and folded.starts is None
        assert self.unicode.fold("café", "basic").starts is None

    def test_basic_composes_and_keeps_accents(self):
        folded = self.unicode.fold("café au lait", "basic")

        assert folded.text == "café au lait"
        assert folded.original(3, 4) == (3, 5)  # the é was two characters
        assert folded.original(5, 7) == (6, 8)  # "au" is after it

    def test_full_folds_accents_and_compatibility_forms(self):
        text = "Café ﬁn ＡBC ½"

        assert self.unicode.fold(text, "full").text == "Cafe fin ABC 1⁄2"

    def test_full_traces_expanded_characters_back_to_the_original(self):
        text = "x ﬁn"
        folded = self.unicode.fold(text, "full")

        assert folded.text == "x fin"
        assert folded.original(2, 5) == (2, 4)  # "ﬁn" is two characters in the original
        assert folded.original(2, 4) == (2, 3)  # "fi" is the one ligature

    def test_a_unit_that_does_not_normalize_piece_by_piece_is_traced_as_a_whole(self):
        # Hangul jamo compose across characters that each start a new unit.
        text = "각 x"

        folded = self.unicode.fold(text, "basic")

        assert folded.text == "각 x"
        assert folded.original(0, 1) == (0, 3)

    def test_levels(self):
        assert self.unicode.levels == ("off", "basic", "full")
        assert self.unicode.identity == "off"
        assert self.unicode.fold("café", "off").text == "café"
        assert self.unicode.char_table("full") is None


class TestLeetspeakNormalizer:
    leet = LeetspeakNormalizer()

    @pytest.mark.parametrize(
        ("level", "text", "folded"),
        [
            ("basic", "h3ll0 p@55w0rd", "heiio password"),
            ("basic", "b8 9ood", "b8 9ood"),  # not in the basic table
            ("standard", "b8 9ood w!n", "bb good win"),
            ("extended", "[lock", "ciock"),
            ("off", "h3ll0", "h3ll0"),
        ],
    )
    def test_folds_single_characters(self, level, text, folded):
        assert self.leet.fold(text, level).text == folded

    def test_positions_never_move(self):
        assert self.leet.fold("h3ll0", "standard").starts is None

    def test_keeps_the_case_of_letters(self):
        assert self.leet.fold("HeLLo", "basic").text == "HeIIo"

    def test_the_character_table_does_the_same(self):
        table = self.leet.char_table("basic")

        assert table is not None and "h3ll0".translate(table) == "heiio"
        assert self.leet.char_table("off") == {}

    def test_multi_character_spellings_are_not_folded_as_one(self):
        folded = self.leet.fold("|\\|ice", "extended").text

        assert len(folded) == len("|\\|ice") and "n" not in folded
