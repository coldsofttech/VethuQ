import pytest
from vethuq_core.settings import InvalidSettingValueError, UpdateSettings
from vethuq_core.storage import Storage

DAY = 24 * 60 * 60


class TestCheckSetting:
    def test_on_by_default(self, storage: Storage):
        assert UpdateSettings.get_check(storage) == "on"

    @pytest.mark.parametrize("value", UpdateSettings.CHECK_VALUES)
    def test_set_and_get(self, storage: Storage, value):
        UpdateSettings.set_check(storage, value)
        assert UpdateSettings.get_check(storage) == value

    def test_rejects_other_values(self, storage: Storage):
        with pytest.raises(InvalidSettingValueError):
            UpdateSettings.set_check(storage, "sometimes")

    def test_reset(self, storage: Storage):
        UpdateSettings.set_check(storage, "off")
        UpdateSettings.reset_check(storage)
        assert UpdateSettings.get_check(storage) == "on"

    def test_unknown_stored_value_means_default(self, storage: Storage):
        storage.upsert_setting(UpdateSettings.CHECK_KEY, "garbage")
        assert UpdateSettings.get_check(storage) == "on"


class TestEnvironmentVariable:
    @pytest.mark.parametrize("value", ["off", "OFF", "0", "false", " no "])
    def test_turns_the_check_off_over_the_setting(self, storage: Storage, monkeypatch, value):
        monkeypatch.setenv(UpdateSettings.ENV_VAR, value)
        UpdateSettings.set_check(storage, "on")
        assert UpdateSettings.disabled_by_environment() is True
        assert UpdateSettings.effective_check(storage) == "off"

    @pytest.mark.parametrize("value", ["", "on", "1", "yes"])
    def test_other_values_leave_the_setting_in_charge(self, storage: Storage, monkeypatch, value):
        monkeypatch.setenv(UpdateSettings.ENV_VAR, value)
        UpdateSettings.set_check(storage, "notify-only")
        assert UpdateSettings.disabled_by_environment() is False
        assert UpdateSettings.effective_check(storage) == "notify-only"

    def test_unset(self, storage: Storage, monkeypatch):
        monkeypatch.delenv(UpdateSettings.ENV_VAR, raising=False)
        assert UpdateSettings.effective_check(storage) == "on"


class TestSnooze:
    def test_not_snoozed_by_default(self, storage: Storage):
        assert UpdateSettings.get_snoozed_until(storage) is None
        assert UpdateSettings.is_snoozed(storage, now=1000.0) is False

    def test_snooze_lasts_the_given_days(self, storage: Storage):
        UpdateSettings.snooze(storage, 2, now=1000.0)
        assert UpdateSettings.get_snoozed_until(storage) == 1000.0 + 2 * DAY
        assert UpdateSettings.is_snoozed(storage, now=1000.0 + DAY) is True
        assert UpdateSettings.is_snoozed(storage, now=1000.0 + 2 * DAY) is False

    def test_default_is_one_day(self, storage: Storage):
        UpdateSettings.snooze(storage, now=0.0)
        assert UpdateSettings.get_snoozed_until(storage) == DAY

    @pytest.mark.parametrize("days", [0, -1])
    def test_days_must_be_positive(self, storage: Storage, days):
        with pytest.raises(InvalidSettingValueError):
            UpdateSettings.snooze(storage, days)

    def test_clear(self, storage: Storage):
        UpdateSettings.snooze(storage, 3, now=0.0)
        UpdateSettings.clear_snooze(storage)
        assert UpdateSettings.get_snoozed_until(storage) is None

    def test_damaged_value_means_not_snoozed(self, storage: Storage):
        storage.upsert_setting(UpdateSettings.SNOOZE_KEY, "tomorrow")
        assert UpdateSettings.is_snoozed(storage, now=0.0) is False


class TestSkip:
    def test_none_by_default(self, storage: Storage):
        assert UpdateSettings.get_skipped_version(storage) is None

    def test_skip_and_clear(self, storage: Storage):
        UpdateSettings.skip_version(storage, " 1.2.0 ")
        assert UpdateSettings.get_skipped_version(storage) == "1.2.0"
        UpdateSettings.clear_skip(storage)
        assert UpdateSettings.get_skipped_version(storage) is None

    def test_rejects_empty(self, storage: Storage):
        with pytest.raises(InvalidSettingValueError):
            UpdateSettings.skip_version(storage, "  ")
