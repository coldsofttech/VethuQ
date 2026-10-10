from __future__ import annotations

import pytest

from vethuq import errors
from vethuq._db import _Database
from vethuq._settings import _Settings, _SourceSettings


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
