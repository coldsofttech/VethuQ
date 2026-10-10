from __future__ import annotations

import json
import sys

import pytest

import vethuq
from tests.language_addons import TELUGU, LanguageAddonFactory
from vethuq import errors


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


@pytest.fixture
def telugu(tmp_path_factory, monkeypatch):
    """Telugu is installed next to English."""
    folder = tmp_path_factory.mktemp("telugu_addon")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    module = LanguageAddonFactory.install(folder, "telugu", [TELUGU])
    yield
    LanguageAddonFactory.forget(module)


def ids(languages):
    return [language.id for language in languages]


class TestLanguage:
    def test_details(self, client):
        english = client.languages.get("en")

        assert (english.id, english.label, english.script) == ("en", "English", "latin")
        assert (english.default, english.installed, english.available) == (True, True, True)
        assert (english.enabled, english.usable, english.reason) == (True, True, "")
        assert english.native_label == ""

    def test_is_frozen(self, client):
        with pytest.raises(AttributeError):
            client.languages.get("en").label = "x"

    def test_to_dict_and_json(self, client):
        language = client.languages.get("en")

        assert language.to_dict() == {
            "id": "en",
            "label": "English",
            "native_label": "",
            "script": "latin",
            "default": True,
            "installed": True,
            "available": True,
            "enabled": True,
            "reason": "",
        }
        assert json.loads(language.to_json()) == language.to_dict()
        assert "\n" in language.to_json(indent=2)


class TestLanguages:
    def test_english_is_there_out_of_the_box(self, client):
        assert ids(client.languages.list_all()) == ["en"]
        assert ids(client.languages.list_enabled()) == ["en"]

    def test_list_all_returns_language_objects(self, client):
        assert all(isinstance(item, vethuq.Language) for item in client.languages.list_all())

    def test_installed_languages_are_listed_default_first(self, client, telugu):
        listed = client.languages.list_all()

        assert ids(listed) == ["en", "te"]
        assert listed[1].native_label == "తెలుగు" and not listed[1].default

    def test_get_unknown_is_none(self, client):
        assert client.languages.get("xx") is None

    def test_get_is_case_insensitive(self, client):
        assert client.languages.get(" EN ").id == "en"

    def test_the_default_is_english(self, client, telugu):
        assert client.languages.default().id == "en"

    def test_the_default_stays_english_when_it_is_disabled(self, client, telugu):
        client.languages.disable("en")
        assert client.languages.default().id == "en"
        assert client.languages.default().enabled is False

    def test_every_listed_language_can_be_used_for_a_source(self, client, telugu, tmp_path):
        listed = ids(client.languages.list_all())

        assert client.sources.create(tmp_path, languages=listed).languages == listed

    def test_languages_object_is_reused(self, client):
        assert client.languages is client.languages

    def test_nothing_is_created_until_first_use(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db")
        client.languages

        assert not (tmp_path / "db").exists()

    def test_close_then_use_again(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "vethuq.db")
        client.languages.list_all()
        client.close()

        assert ids(client.languages.list_all()) == ["en"]
        client.close()


class TestEnableAndDisable:
    def test_disable_and_enable(self, client, telugu):
        disabled = client.languages.disable("te")

        assert disabled.enabled is False and disabled.usable is False
        assert ids(client.languages.list_enabled()) == ["en"]
        assert ids(client.languages.list_all()) == ["en", "te"]
        assert client.languages.enable("te").usable is True
        assert ids(client.languages.list_enabled()) == ["en", "te"]

    def test_it_survives_a_reopen(self, tmp_path, telugu):
        path = tmp_path / "vethuq.db"
        with vethuq.VethuQ(path) as first:
            first.languages.disable("te")
        with vethuq.VethuQ(path) as second:
            assert second.languages.get("te").enabled is False

    def test_the_last_language_cannot_be_disabled(self, client):
        with pytest.raises(errors.LastLanguageError) as excinfo:
            client.languages.disable("en")
        assert excinfo.value.exit_code == 17 and excinfo.value.hint

    def test_english_can_be_disabled_when_another_language_is_on(self, client, telugu):
        client.languages.disable("en")

        assert ids(client.languages.list_enabled()) == ["te"]
        with pytest.raises(errors.LastLanguageError):
            client.languages.disable("te")

    def test_unknown_languages_are_refused(self, client):
        with pytest.raises(errors.LanguageUnavailableError):
            client.languages.disable("xx")
        with pytest.raises(errors.LanguageUnavailableError):
            client.languages.enable("xx")


class TestDisabledLanguagesAreNotUsed:
    def test_a_source_cannot_use_a_disabled_language(self, client, telugu, tmp_path):
        client.languages.disable("te")

        with pytest.raises(errors.LanguageUnavailableError) as excinfo:
            client.sources.create(tmp_path, languages=["te"])
        assert "disabled" in str(excinfo.value)

    def test_set_languages_refuses_it_too(self, client, telugu, tmp_path):
        source = client.sources.create(tmp_path)
        client.languages.disable("te")

        with pytest.raises(errors.LanguageUnavailableError):
            client.sources.set_languages(source.id, ["te"])

    def test_it_works_again_once_enabled(self, client, telugu, tmp_path):
        client.languages.disable("te")
        client.languages.enable("te")

        assert client.sources.create(tmp_path, languages=["te"]).languages == ["te"]

    def test_a_source_keeps_a_language_disabled_after_it_was_chosen(self, client, telugu, tmp_path):
        source = client.sources.create(tmp_path, languages=["te"])
        client.languages.disable("te")

        assert client.sources.get(source.id).languages == ["te"]

    def test_filtering_by_a_disabled_language_still_works(self, client, telugu, tmp_path):
        source = client.sources.create(tmp_path, languages=["te"])
        client.languages.disable("te")

        assert [s.id for s in client.sources.list(language="te")] == [source.id]

    def test_filtering_by_an_installed_language_nobody_uses_is_empty(self, client, telugu):
        assert client.sources.list(language="te") == []

    def test_a_language_whose_addon_is_missing_is_refused(self, client, tmp_path):
        with pytest.raises(errors.LanguageUnavailableError, match="Unknown language 'te'"):
            client.sources.create(tmp_path, languages=["te"])


class TestDefaultLanguagesSetting:
    def test_english_unless_changed(self, client):
        assert client.settings.languages.get_languages() == ["en"]

    def test_set_and_reset(self, client, telugu):
        assert client.settings.languages.set_languages(["te", "en"]) == ["te", "en"]
        assert client.settings.languages.get_languages() == ["te", "en"]
        client.settings.languages.reset_languages()
        assert client.settings.languages.get_languages() == ["en"]

    def test_unusable_languages_are_refused(self, client, telugu):
        client.languages.disable("te")
        with pytest.raises(errors.LanguageUnavailableError):
            client.settings.languages.set_languages(["te"])
        with pytest.raises(errors.LanguageUnavailableError):
            client.settings.languages.set_languages(["xx"])

    def test_empty_is_refused(self, client):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.languages.set_languages([])

    def test_disabling_a_language_removes_it_from_the_setting(self, client, telugu):
        client.settings.languages.set_languages(["en", "te"])
        client.languages.disable("te")

        assert client.settings.languages.get_languages() == ["en"]

    def test_if_the_only_saved_language_is_disabled_english_applies(self, client, telugu):
        client.settings.languages.set_languages(["te"])
        client.languages.disable("te")

        assert client.settings.languages.get_languages() == ["en"]
