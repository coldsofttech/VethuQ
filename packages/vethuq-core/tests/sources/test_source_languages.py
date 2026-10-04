import pytest
from vethuq_core.languages import UnknownLanguageError
from vethuq_core.sources import SourceNotFoundError, Sources


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "docs"
    path.mkdir()
    return path


class TestAddWithLanguages:
    def test_a_source_has_no_languages_unless_given(self, storage, folder):
        source = Sources.add(storage, folder)

        assert source.languages is None
        assert "languages" not in source.to_dict()

    def test_languages_are_stored_normalized(self, storage, folder):
        source = Sources.add(storage, folder, languages="te, en")

        assert source.languages == "en,te"
        assert source.to_dict()["languages"] == "en,te"

    def test_auto_is_stored(self, storage, folder):
        assert Sources.add(storage, folder, languages="auto").languages == "auto"

    def test_an_unknown_language_is_refused_and_nothing_is_added(self, storage, folder):
        with pytest.raises(UnknownLanguageError):
            Sources.add(storage, folder, languages="xx")

        assert Sources.list_all(storage) == []

    def test_readding_a_removed_source_with_languages_sets_them(self, storage, folder):
        source = Sources.add(storage, folder)
        Sources.remove(storage, source.id)

        again = Sources.add(storage, folder, languages="te")

        assert again.languages == "te"

    def test_readding_a_removed_source_keeps_its_languages_if_none_given(self, storage, folder):
        source = Sources.add(storage, folder, languages="te")
        Sources.remove(storage, source.id)

        assert Sources.add(storage, folder).languages == "te"


class TestSetLanguages:
    def test_sets_and_clears(self, storage, folder):
        source = Sources.add(storage, folder)

        assert Sources.set_languages(storage, source.id, "te").languages == "te"
        assert Sources.set_languages(storage, str(folder), ["te", "en"]).languages == "en,te"
        assert Sources.set_languages(storage, source.id, None).languages is None

    def test_an_unknown_language_is_refused_and_the_old_value_kept(self, storage, folder):
        source = Sources.add(storage, folder, languages="te")

        with pytest.raises(UnknownLanguageError):
            Sources.set_languages(storage, source.id, "xx")

        assert Sources.get(storage, source.id).languages == "te"

    def test_an_unknown_source_is_refused(self, storage):
        with pytest.raises(SourceNotFoundError):
            Sources.set_languages(storage, 999, "te")

    def test_it_is_part_of_what_list_returns(self, storage, folder):
        Sources.add(storage, folder, languages="te")

        assert [s.languages for s in Sources.list_all(storage)] == ["te"]
