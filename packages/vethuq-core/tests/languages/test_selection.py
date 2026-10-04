import pytest
from vethuq_core.errors import LanguageUnavailableError
from vethuq_core.languages import Candidates, LanguageSelection, UnknownLanguageError

ENABLED = ["en", "te"]


class TestParse:
    def test_none_and_empty_choose_nothing(self):
        assert LanguageSelection.parse(None) is None
        assert LanguageSelection.parse("") is None
        assert LanguageSelection.parse(" , ") is None
        assert LanguageSelection.parse([]) is None

    def test_one_language(self):
        assert LanguageSelection.parse("te") == ["te"]

    def test_several_are_put_in_catalog_order_without_duplicates(self):
        assert LanguageSelection.parse("te,en") == ["en", "te"]
        assert LanguageSelection.parse("te, te ,EN") == ["en", "te"]

    def test_repeated_flags_and_commas_mix(self):
        assert LanguageSelection.parse(["te", "en,te"]) == ["en", "te"]

    def test_auto_stands_alone(self):
        assert LanguageSelection.parse("auto") == ["auto"]
        assert LanguageSelection.parse("en, AUTO") == ["auto"]

    def test_an_unknown_language_is_refused_with_the_known_ones(self):
        with pytest.raises(UnknownLanguageError, match="Unknown language 'xx'.*en, te"):
            LanguageSelection.parse("en,xx")

    def test_format_joins_with_commas(self):
        assert LanguageSelection.format(["en", "te"]) == "en,te"


class TestResolve:
    def test_nothing_requested_is_the_default_language_alone(self):
        candidates = LanguageSelection.resolve(None, explicit=False, enabled=ENABLED)

        assert candidates == Candidates(("en",), False)
        assert not candidates.needs_detection

    def test_auto_is_every_enabled_language_default_first(self):
        candidates = LanguageSelection.resolve(["auto"], explicit=False, enabled=ENABLED)

        assert candidates.ids == ("en", "te")
        assert candidates.first == "en"
        assert candidates.rest == ("te",)
        assert candidates.needs_detection

    def test_auto_with_only_english_is_english_alone(self):
        candidates = LanguageSelection.resolve(["auto"], explicit=False, enabled=["en"])

        assert candidates.ids == ("en",)
        assert not candidates.needs_detection

    def test_a_language_that_is_not_enabled_is_refused_with_how_to_install_it(self):
        with pytest.raises(LanguageUnavailableError) as raised:
            LanguageSelection.resolve(["te"], explicit=True, enabled=["en"])

        assert "Telugu" in raised.value.message
        assert "pip install vethuq[lang-te]" in raised.value.hint
        assert raised.value.exit_code == 16

    def test_a_list_keeps_its_order(self):
        assert LanguageSelection.resolve(["en", "te"], explicit=True, enabled=ENABLED).ids == (
            "en",
            "te",
        )


class TestChoiceSource:
    def test_a_chosen_language_is_manual_and_a_defaulted_one_is_default(self):
        assert Candidates(("te",), explicit=True).choice_source == "manual"
        assert Candidates(("en",), explicit=False).choice_source == "default"
