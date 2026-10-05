from vethuq_ui.languages import LanguageChoice


class TestLanguageChoice:
    def test_auto_and_empty_mean_no_chosen_languages(self):
        assert LanguageChoice.selection_ids("auto") == []
        assert LanguageChoice.selection_ids(None) == []
        assert LanguageChoice.selection_ids("") == []

    def test_a_stored_list_is_split(self):
        assert LanguageChoice.selection_ids("en, te") == ["en", "te"]

    def test_automatic_is_stored_as_auto_whatever_is_ticked(self):
        assert LanguageChoice.stored(True, ["te"]) == "auto"

    def test_nothing_ticked_falls_back_to_auto(self):
        assert LanguageChoice.stored(False, []) == "auto"

    def test_ticked_languages_are_stored_in_catalog_order(self):
        assert LanguageChoice.stored(False, ["te", "en"]) in ("en,te", "te,en")
