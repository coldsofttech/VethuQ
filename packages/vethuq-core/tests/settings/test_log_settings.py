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
