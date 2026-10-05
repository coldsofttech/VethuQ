import pytest
from vethuq_core.settings import SearchSettings
from vethuq_core.settings.settings import InvalidSettingValueError, Settings
from vethuq_core.storage import Storage


class TestSemanticThreshold:
    def test_defaults_to_balanced(self, storage: Storage):
        assert SearchSettings.get_semantic_threshold_setting(storage) == "balanced"
        assert SearchSettings.get_semantic_threshold(storage) == 0.80

    @pytest.mark.parametrize(
        ("value", "ratio"),
        [
            ("strict", 0.86),
            ("Balanced", 0.80),
            ("loose", 0.75),
            ("0.9", 0.9),
            ("85%", 0.85),
            ("70", 0.7),
        ],
    )
    def test_roundtrip(self, storage: Storage, value, ratio):
        SearchSettings.set_semantic_threshold(storage, value)
        assert SearchSettings.get_semantic_threshold_setting(storage) == value.lower()
        assert SearchSettings.get_semantic_threshold(storage) == pytest.approx(ratio)

    @pytest.mark.parametrize("value", ["", "tight", "0", "-1", "101", "1.5", "nan", "abc"])
    def test_invalid_values_are_rejected(self, storage: Storage, value):
        with pytest.raises(InvalidSettingValueError):
            SearchSettings.set_semantic_threshold(storage, value)
        assert SearchSettings.get_semantic_threshold_setting(storage) == "balanced"

    def test_a_corrupt_stored_value_falls_back_to_the_default(self, storage: Storage):
        Settings.set(storage, SearchSettings.SEMANTIC_THRESHOLD_KEY, "garbage")
        assert SearchSettings.get_semantic_threshold(storage) == 0.80

    def test_presets_are_ordered_strict_to_loose(self):
        presets = SearchSettings.SEMANTIC_PRESETS
        assert presets["strict"] > presets["balanced"] > presets["loose"] > 0

    def test_it_is_independent_of_the_fuzzy_threshold(self, storage: Storage):
        SearchSettings.set_fuzzy_threshold(storage, "strict")
        assert SearchSettings.get_semantic_threshold(storage) == 0.80
        SearchSettings.set_semantic_threshold(storage, "loose")
        assert SearchSettings.get_fuzzy_threshold(storage) == 0.90

    def test_fuzzy_parsing_is_unchanged(self):
        assert SearchSettings.parse_fuzzy_threshold("strict") == 0.9
        with pytest.raises(InvalidSettingValueError, match="strict.*balanced.*loose"):
            SearchSettings.parse_fuzzy_threshold("nope")


class TestSemanticLimit:
    def test_defaults_to_25(self, storage: Storage):
        assert SearchSettings.get_semantic_limit(storage) == 25

    def test_roundtrip(self, storage: Storage):
        SearchSettings.set_semantic_limit(storage, "40")
        assert SearchSettings.get_semantic_limit(storage) == 40

    @pytest.mark.parametrize("value", ["0", "-3", "1001", "ten", "2.5", "", True, 2.5])
    def test_invalid_values_are_rejected(self, storage: Storage, value):
        with pytest.raises(InvalidSettingValueError):
            SearchSettings.set_semantic_limit(storage, value)

    def test_a_corrupt_stored_value_falls_back_to_the_default(self, storage: Storage):
        Settings.set(storage, SearchSettings.SEMANTIC_LIMIT_KEY, "many")
        assert SearchSettings.get_semantic_limit(storage) == 25


class TestSemanticCombine:
    def test_defaults_to_off(self, storage: Storage):
        assert SearchSettings.get_semantic_combine(storage) == "off"

    @pytest.mark.parametrize("value", ["off", "full-text", "lexical", " Full-Text "])
    def test_roundtrip(self, storage: Storage, value):
        SearchSettings.set_semantic_combine(storage, value)
        assert SearchSettings.get_semantic_combine(storage) == value.strip().lower()

    @pytest.mark.parametrize("value", ["", "fuzzy", "like", "all", "on"])
    def test_other_values_are_rejected(self, storage: Storage, value):
        with pytest.raises(InvalidSettingValueError, match="off, full-text, lexical"):
            SearchSettings.set_semantic_combine(storage, value)

    def test_a_corrupt_stored_value_falls_back_to_off(self, storage: Storage):
        Settings.set(storage, SearchSettings.SEMANTIC_COMBINE_KEY, "fuzzy")
        assert SearchSettings.get_semantic_combine(storage) == "off"


class TestEngineSetting:
    def test_semantic_can_be_the_default_engine(self, storage: Storage):
        SearchSettings.set_engine(storage, "semantic")
        assert SearchSettings.get_engine(storage) == "semantic"
