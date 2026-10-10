from __future__ import annotations

import pytest

from vethuq import errors
from vethuq._db import _Database
from vethuq._settings import _LogSettings, _Settings, _SourceSettings, _UpdateSettings
from vethuq.enums import LogLevel, UpdateCheckMode


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


class TestUpdateSettings:
    def test_defaults(self, database, monkeypatch):
        monkeypatch.delenv("VETHUQ_UPDATE_CHECK", raising=False)
        with database.session() as session:
            view = _UpdateSettings.read(session)

        assert view.mode is UpdateCheckMode.ON
        assert (view.disabled_by_environment, view.snoozed) == (False, False)
        assert view.skipped_version is None

    @pytest.mark.parametrize("mode", [UpdateCheckMode.NOTIFY_ONLY, UpdateCheckMode.OFF, "on"])
    def test_set_the_check_mode(self, database, mode):
        with database.session() as session:
            _UpdateSettings.set_check(session, mode)

        with database.session() as session:
            assert _UpdateSettings.get_check(session) is UpdateCheckMode(mode)

    @pytest.mark.parametrize("mode", ["sometimes", "", None, 3])
    def test_a_bad_mode_is_rejected_with_the_options(self, database, mode):
        with pytest.raises(errors.InvalidSettingValueError) as excinfo:
            with database.session() as session:
                _UpdateSettings.set_check(session, mode)

        assert "on, notify-only, off" in excinfo.value.hint

    def test_reset_the_check_mode(self, database):
        with database.session() as session:
            _UpdateSettings.set_check(session, "off")
            _UpdateSettings.reset_check(session)

        with database.session() as session:
            assert _UpdateSettings.get_check(session) is UpdateCheckMode.ON

    def test_a_damaged_saved_mode_falls_back(self, database):
        with database.session() as session:
            _Settings.set(session, "update_check", "whenever")

        with database.session() as session:
            assert _UpdateSettings.get_check(session) is UpdateCheckMode.ON

    @pytest.mark.parametrize("value", ["off", "0", "false", "no", "disable", "disabled", " OFF "])
    def test_the_environment_can_switch_the_check_off(self, database, monkeypatch, value):
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", value)
        with database.session() as session:
            _UpdateSettings.set_check(session, "on")
            view = _UpdateSettings.read(session)

        assert _UpdateSettings.disabled_by_environment() is True
        assert (view.mode, view.disabled_by_environment) == (UpdateCheckMode.OFF, True)

    @pytest.mark.parametrize("value", ["", "on", "1", "yes", "maybe"])
    def test_other_environment_values_leave_the_setting_in_charge(
        self, database, monkeypatch, value
    ):
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", value)
        with database.session() as session:
            _UpdateSettings.set_check(session, "notify-only")
            view = _UpdateSettings.read(session)

        assert view.mode is UpdateCheckMode.NOTIFY_ONLY and view.disabled_by_environment is False

    def test_snooze(self, database):
        with database.session() as session:
            _UpdateSettings.snooze(session, 2, now=1000.0)

        with database.session() as session:
            assert _UpdateSettings.get_snoozed_until(session) == 1000.0 + 2 * 86400
            assert _UpdateSettings.is_snoozed(session, now=1000.0 + 86400) is True
            assert _UpdateSettings.is_snoozed(session, now=1000.0 + 3 * 86400) is False

    def test_snooze_defaults_to_one_day(self, database):
        with database.session() as session:
            _UpdateSettings.snooze(session, _UpdateSettings.DEFAULT_SNOOZE_DAYS, now=0.0)

        with database.session() as session:
            assert _UpdateSettings.get_snoozed_until(session) == 86400.0

    @pytest.mark.parametrize("days", [0, -1, "1", None, True])
    def test_a_bad_snooze_is_rejected(self, database, days):
        with pytest.raises(errors.InvalidSettingValueError):
            with database.session() as session:
                _UpdateSettings.snooze(session, days)

    def test_clear_snooze(self, database):
        with database.session() as session:
            _UpdateSettings.snooze(session, 1)
            _UpdateSettings.clear_snooze(session)

        with database.session() as session:
            assert _UpdateSettings.get_snoozed_until(session) is None
            assert _UpdateSettings.is_snoozed(session) is False

    def test_a_damaged_snooze_is_ignored(self, database):
        with database.session() as session:
            _Settings.set(session, "update_snoozed_until", "tomorrow")

        with database.session() as session:
            assert _UpdateSettings.get_snoozed_until(session) is None

    def test_skip_a_version(self, database):
        with database.session() as session:
            _UpdateSettings.skip_version(session, " 2.0.0 ")

        with database.session() as session:
            assert _UpdateSettings.get_skipped_version(session) == "2.0.0"
            assert _UpdateSettings.read(session).skipped_version == "2.0.0"

    @pytest.mark.parametrize("version", ["", "   ", None, 2])
    def test_a_bad_version_to_skip_is_rejected(self, database, version):
        with pytest.raises(errors.InvalidSettingValueError):
            with database.session() as session:
                _UpdateSettings.skip_version(session, version)

    def test_clear_skip(self, database):
        with database.session() as session:
            _UpdateSettings.skip_version(session, "2.0.0")
            _UpdateSettings.clear_skip(session)

        with database.session() as session:
            assert _UpdateSettings.get_skipped_version(session) is None
