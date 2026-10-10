from __future__ import annotations

import pytest

from vethuq import errors
from vethuq._db import _Database
from vethuq._settings import _LogSettings, _Settings, _SourceSettings
from vethuq.enums import LogLevel


@pytest.fixture
def database(tmp_path):
    database = _Database(tmp_path / "db" / "vethuq.db")
    yield database
    database.dispose()


class TestSettings:
    def test_a_setting_with_no_value_is_none(self, database):
        with database.session() as session:
            assert _Settings.get(session, "missing") is None

    def test_set_then_get(self, database):
        with database.session() as session:
            _Settings.set(session, "k", "v")

        with database.session() as session:
            assert _Settings.get(session, "k") == "v"

    def test_set_replaces_the_value(self, database):
        with database.session() as session:
            _Settings.set(session, "k", "1")
            _Settings.set(session, "k", "2")

        with database.session() as session:
            assert _Settings.get(session, "k") == "2"

    def test_reset_forgets_the_value(self, database):
        with database.session() as session:
            _Settings.set(session, "k", "v")
            _Settings.reset(session, "k")

        with database.session() as session:
            assert _Settings.get(session, "k") is None

    def test_reset_of_an_unset_setting_is_harmless(self, database):
        with database.session() as session:
            _Settings.reset(session, "never-set")


class TestSourceSettings:
    def test_removed_retention_defaults_to_seven_days(self, database):
        with database.session() as session:
            assert _SourceSettings.get_removed_retention_minutes(session) == 7 * 24 * 60

    def test_set_then_get(self, database):
        with database.session() as session:
            _SourceSettings.set_removed_retention_minutes(session, 90)

        with database.session() as session:
            assert _SourceSettings.get_removed_retention_minutes(session) == 90

    def test_zero_is_allowed(self, database):
        with database.session() as session:
            _SourceSettings.set_removed_retention_minutes(session, 0)

        with database.session() as session:
            assert _SourceSettings.get_removed_retention_minutes(session) == 0

    def test_reset_returns_to_the_default(self, database):
        with database.session() as session:
            _SourceSettings.set_removed_retention_minutes(session, 5)
            _SourceSettings.reset_removed_retention_minutes(session)

        with database.session() as session:
            assert _SourceSettings.get_removed_retention_minutes(session) == 10080

    @pytest.mark.parametrize("value", [-1, 1.5, "10", None, True])
    def test_invalid_values_are_rejected(self, database, value):
        with pytest.raises(errors.InvalidSettingValueError) as excinfo:
            with database.session() as session:
                _SourceSettings.set_removed_retention_minutes(session, value)

        assert excinfo.value.exit_code == 31
        assert "retention" in excinfo.value.message

    def test_a_rejected_value_leaves_the_setting_alone(self, database):
        with database.session() as session:
            _SourceSettings.set_removed_retention_minutes(session, 30)
        with pytest.raises(errors.InvalidSettingValueError):
            with database.session() as session:
                _SourceSettings.set_removed_retention_minutes(session, -5)

        with database.session() as session:
            assert _SourceSettings.get_removed_retention_minutes(session) == 30

    def test_a_damaged_saved_value_falls_back_to_the_default(self, database):
        with database.session() as session:
            _Settings.set(session, _SourceSettings.REMOVED_RETENTION_MINUTES_KEY, "abc")

        with database.session() as session:
            assert _SourceSettings.get_removed_retention_minutes(session) == 10080


class TestLogSettings:
    def test_defaults(self, database):
        with database.session() as session:
            assert _LogSettings.get_level(session) is LogLevel.INFO
            assert _LogSettings.get_retention_days(session) == 15

    @pytest.mark.parametrize("level", [LogLevel.DEBUG, LogLevel.ERROR, "warning"])
    def test_set_level(self, database, level):
        with database.session() as session:
            _LogSettings.set_level(session, level)

        with database.session() as session:
            assert _LogSettings.get_level(session) is LogLevel(level)

    @pytest.mark.parametrize("level", ["loud", "", None, 3])
    def test_a_bad_level_is_rejected_and_lists_the_options(self, database, level):
        with pytest.raises(errors.InvalidSettingValueError) as excinfo:
            with database.session() as session:
                _LogSettings.set_level(session, level)

        assert "debug, info, warning, error" in excinfo.value.hint
        assert excinfo.value.exit_code == 31

    def test_reset_level(self, database):
        with database.session() as session:
            _LogSettings.set_level(session, "error")
            _LogSettings.reset_level(session)

        with database.session() as session:
            assert _LogSettings.get_level(session) is LogLevel.INFO

    def test_level_is_stored_as_its_value(self, database):
        with database.session() as session:
            _LogSettings.set_level(session, LogLevel.DEBUG)

        with database.session() as session:
            assert _Settings.get(session, "log_level") == "debug"

    def test_a_damaged_saved_level_falls_back(self, database):
        with database.session() as session:
            _Settings.set(session, "log_level", "loud")

        with database.session() as session:
            assert _LogSettings.get_level(session) is LogLevel.INFO

    def test_set_retention(self, database):
        with database.session() as session:
            _LogSettings.set_retention_days(session, 30)

        with database.session() as session:
            assert _LogSettings.get_retention_days(session) == 30

    @pytest.mark.parametrize("days", [0, -1, 1.5, "7", None, True])
    def test_bad_retention_is_rejected(self, database, days):
        with pytest.raises(errors.InvalidSettingValueError) as excinfo:
            with database.session() as session:
                _LogSettings.set_retention_days(session, days)

        assert "retention" in excinfo.value.message

    def test_one_day_is_the_least(self, database):
        with database.session() as session:
            _LogSettings.set_retention_days(session, 1)

        with database.session() as session:
            assert _LogSettings.get_retention_days(session) == 1

    def test_reset_retention(self, database):
        with database.session() as session:
            _LogSettings.set_retention_days(session, 2)
            _LogSettings.reset_retention_days(session)

        with database.session() as session:
            assert _LogSettings.get_retention_days(session) == 15

    @pytest.mark.parametrize("saved", ["abc", "0", "-4"])
    def test_a_damaged_saved_retention_falls_back(self, database, saved):
        with database.session() as session:
            _Settings.set(session, "log_retention_days", saved)

        with database.session() as session:
            assert _LogSettings.get_retention_days(session) == 15
