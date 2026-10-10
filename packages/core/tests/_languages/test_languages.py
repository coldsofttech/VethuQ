from __future__ import annotations

import pytest
from sqlalchemy import select

from vethuq._db import _Database, _Language
from vethuq._errors import _InvalidSettingValueError
from vethuq._languages import _Languages
from vethuq._settings import _LanguageSettings
from vethuq.errors import LanguageUnavailableError, LastLanguageError
from vethuq_addon_api import LanguageSpec

EN = LanguageSpec("en", "English", script="latin", default=True)
TE = LanguageSpec("te", "Telugu", native_label="తెలుగు", script="telugu")


@pytest.fixture
def database(tmp_path):
    database = _Database(tmp_path / "db" / "vethuq.db")
    yield database
    database.dispose()


@pytest.fixture
def session(database):
    with database.session() as session:
        yield session


def ids(views):
    return [view.id for view in views]


class TestViews:
    def test_nothing_installed_nothing_known(self, session):
        assert _Languages.views(session, []) == []

    def test_the_default_comes_first_then_by_id(self, session):
        zz = LanguageSpec("zz", "Z")
        assert ids(_Languages.views(session, [zz, TE, EN])) == ["en", "te", "zz"]

    def test_a_view_describes_the_language(self, session):
        (en,) = _Languages.views(session, [EN])
        assert (en.label, en.script, en.default) == ("English", "latin", True)
        assert (en.installed, en.available, en.enabled, en.usable) == (True, True, True, True)

    def test_an_unavailable_language_is_not_usable_and_says_why(self, session):
        lapsed = LanguageSpec("te", "Telugu", available=False, reason="its licence has lapsed")
        te = next(v for v in _Languages.views(session, [EN, lapsed]) if v.id == "te")
        assert (te.installed, te.available, te.usable) == (True, False, False)
        assert te.reason == "its licence has lapsed"

    def test_a_remembered_language_without_its_addon_is_listed_as_not_installed(self, session):
        session.add(_Language(language="te"))
        session.flush()
        te = next(v for v in _Languages.views(session, [EN]) if v.id == "te")
        assert (te.installed, te.available, te.label) == (False, False, "te")

    def test_find_is_case_insensitive_and_none_for_unknown(self, session):
        assert _Languages.find(session, [EN], " EN ").id == "en"
        assert _Languages.find(session, [EN], "xx") is None


class TestDefault:
    def test_the_default_spec(self):
        assert _Languages.default([TE, EN]) is EN

    def test_without_one(self):
        with pytest.raises(LanguageUnavailableError, match="No default language"):
            _Languages.default([TE])


class TestRows:
    def test_available_languages_get_rows_in_spec_order(self, session):
        _Languages.ensure_rows(session, [EN, TE])
        _Languages.ensure_rows(session, [EN, TE])
        rows = session.execute(select(_Language.id, _Language.language)).all()
        assert [tuple(r) for r in rows] == [(1, "en"), (2, "te")]

    def test_unavailable_languages_get_none(self, session):
        _Languages.ensure_rows(session, [EN, LanguageSpec("te", "Telugu", available=False)])
        assert session.scalars(select(_Language.language)).all() == ["en"]


class TestDisableAndEnable:
    def test_disabling_and_enabling(self, session):
        specs = [EN, TE]
        assert _Languages.disable(session, specs, "te").enabled is False
        assert _LanguageSettings.get_disabled(session) == ["te"]
        assert _Languages.usable_ids(session, specs) == ["en"]
        assert _Languages.enable(session, specs, "te").enabled is True
        assert _LanguageSettings.get_disabled(session) == []

    def test_disabling_twice_is_harmless(self, session):
        _Languages.disable(session, [EN, TE], "te")
        _Languages.disable(session, [EN, TE], "te")
        assert _LanguageSettings.get_disabled(session) == ["te"]

    def test_the_last_usable_language_cannot_be_disabled(self, session):
        with pytest.raises(LastLanguageError) as excinfo:
            _Languages.disable(session, [EN], "en")
        assert excinfo.value.hint

    def test_the_last_usable_one_counts_only_usable_languages(self, session):
        lapsed = LanguageSpec("te", "Telugu", available=False, reason="x")
        with pytest.raises(LastLanguageError):
            _Languages.disable(session, [EN, lapsed], "en")

    def test_english_can_be_disabled_while_another_language_is_usable(self, session):
        assert _Languages.disable(session, [EN, TE], "en").enabled is False
        with pytest.raises(LastLanguageError):
            _Languages.disable(session, [EN, TE], "te")

    def test_an_unavailable_language_can_be_disabled_freely(self, session):
        lapsed = LanguageSpec("te", "Telugu", available=False, reason="x")
        assert _Languages.disable(session, [EN, lapsed], "te").enabled is False

    def test_an_unavailable_language_cannot_be_enabled(self, session):
        lapsed = LanguageSpec("te", "Telugu", available=False, reason="its licence has lapsed")
        with pytest.raises(LanguageUnavailableError, match="licence has lapsed"):
            _Languages.enable(session, [EN, lapsed], "te")

    @pytest.mark.parametrize("action", [_Languages.disable, _Languages.enable])
    def test_unknown_languages_are_refused(self, session, action):
        with pytest.raises(LanguageUnavailableError, match="Unknown language 'xx'"):
            action(session, [EN], "xx")

    def test_disabling_drops_it_from_the_default_languages(self, session):
        _Languages.set_default_ids(session, [EN, TE], ["en", "te"])
        _Languages.disable(session, [EN, TE], "te")
        assert _LanguageSettings.get_default(session) == ["en"]


class TestDefaultLanguages:
    def test_the_system_default_unless_changed(self, session):
        assert _Languages.default_ids(session, [EN, TE]) == ["en"]

    def test_setting_and_reading(self, session):
        assert _Languages.set_default_ids(session, [EN, TE], [" TE ", "en", "te"]) == ["te", "en"]
        assert _Languages.default_ids(session, [EN, TE]) == ["te", "en"]

    def test_empty_is_refused(self, session):
        with pytest.raises(_InvalidSettingValueError):
            _Languages.set_default_ids(session, [EN], [])

    def test_a_list_is_required(self, session):
        with pytest.raises(TypeError):
            _Languages.set_default_ids(session, [EN], "en")

    def test_unusable_languages_are_refused(self, session):
        _Languages.disable(session, [EN, TE], "te")
        with pytest.raises(LanguageUnavailableError, match="disabled"):
            _Languages.set_default_ids(session, [EN, TE], ["te"])

    def test_a_saved_language_that_stops_being_usable_falls_back(self, session):
        _Languages.set_default_ids(session, [EN, TE], ["te"])
        assert _Languages.default_ids(session, [EN]) == ["en"]  # te's add-on is gone

    def test_falls_back_to_english_even_if_it_is_switched_off(self, session):
        _LanguageSettings.set_disabled(session, ["en"])
        assert _Languages.default_ids(session, [EN]) == ["en"]


class TestValidate:
    def test_usable_languages_pass_and_get_rows(self, session):
        rows = _Languages.validate(session, [EN, TE], ["te", "en"])
        assert [r.language for r in rows] == ["en", "te"]

    def test_unknown(self, session):
        with pytest.raises(LanguageUnavailableError) as excinfo:
            _Languages.validate(session, [EN], ["xx", "yy"])
        assert "Unknown languages 'xx', 'yy'" in str(excinfo.value)
        assert "Available languages: en" in str(excinfo.value)

    def test_not_installed(self, session):
        session.add(_Language(language="te"))
        session.flush()
        with pytest.raises(LanguageUnavailableError, match="add-on isn't installed"):
            _Languages.validate(session, [EN], ["te"])

    def test_unavailable(self, session):
        lapsed = LanguageSpec("te", "Telugu", available=False, reason="its licence has lapsed")
        with pytest.raises(LanguageUnavailableError, match="licence has lapsed"):
            _Languages.validate(session, [EN, lapsed], ["te"])

    def test_disabled(self, session):
        _Languages.disable(session, [EN, TE], "te")
        with pytest.raises(LanguageUnavailableError, match="disabled") as excinfo:
            _Languages.validate(session, [EN, TE], ["te"])
        assert "languages.enable('te')" in excinfo.value.hint
