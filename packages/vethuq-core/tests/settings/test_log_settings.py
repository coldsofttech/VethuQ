import pytest
from vethuq_core.settings import LogSettings
from vethuq_core.storage import Storage


class TestLogSettings:
    def test_level_defaults_to_info_and_validates(self, storage: Storage):
        assert LogSettings.get_level(storage) == "info"

        LogSettings.set_level(storage, "warning")
        assert LogSettings.get_level(storage) == "warning"

        with pytest.raises(ValueError):
            LogSettings.set_level(storage, "loud")

    def test_retention_defaults_to_15_and_validates(self, storage: Storage):
        assert LogSettings.get_retention_days(storage) == 15

        LogSettings.set_retention_days(storage, 3)
        assert LogSettings.get_retention_days(storage) == 3

        with pytest.raises(ValueError):
            LogSettings.set_retention_days(storage, 0)


class TestLogSettingsReset:
    def test_reset_level_goes_back_to_info(self, storage):
        LogSettings.set_level(storage, "debug")

        LogSettings.reset_level(storage)

        assert LogSettings.get_level(storage) == LogSettings.DEFAULT_LEVEL

    def test_reset_retention_goes_back_to_default(self, storage):
        LogSettings.set_retention_days(storage, 30)

        LogSettings.reset_retention_days(storage)

        assert LogSettings.get_retention_days(storage) == LogSettings.DEFAULT_RETENTION_DAYS
