import pytest
from vethuq_core.settings import InvalidSettingValueError, OcrSettings


class TestLanguagesSetting:
    def test_the_default_is_auto(self, storage):
        assert OcrSettings.get_languages(storage) == "auto"

    def test_a_language_is_stored_as_given(self, storage):
        assert OcrSettings.set_languages(storage, "te") == "te"
        assert OcrSettings.get_languages(storage) == "te"

    def test_several_are_stored_in_catalog_order(self, storage):
        assert OcrSettings.set_languages(storage, "te, en") == "en,te"
        assert OcrSettings.get_languages(storage) == "en,te"

    def test_a_list_is_accepted(self, storage):
        assert OcrSettings.set_languages(storage, ["te", "en"]) == "en,te"

    def test_auto(self, storage):
        OcrSettings.set_languages(storage, "te")

        OcrSettings.set_languages(storage, "auto")

        assert OcrSettings.get_languages(storage) == "auto"

    def test_an_unknown_language_is_refused_and_the_setting_kept(self, storage):
        OcrSettings.set_languages(storage, "te")

        with pytest.raises(InvalidSettingValueError, match="Unknown language 'xx'"):
            OcrSettings.set_languages(storage, "xx")

        assert OcrSettings.get_languages(storage) == "te"

    @pytest.mark.parametrize("value", ["", " , ", []])
    def test_nothing_is_refused(self, storage, value):
        with pytest.raises(InvalidSettingValueError):
            OcrSettings.set_languages(storage, value)

    def test_it_is_a_value_error_like_the_other_settings(self, storage):
        with pytest.raises(ValueError):
            OcrSettings.set_languages(storage, "xx")

    def test_reset_goes_back_to_auto(self, storage):
        OcrSettings.set_languages(storage, "te")

        OcrSettings.reset_languages(storage)

        assert OcrSettings.get_languages(storage) == "auto"
