import pytest
from vethuq_core.settings import LogSettings


class TestLogSettings:
    def test_level_defaults_to_info_and_validates(self, conn):
        assert LogSettings.get_level(conn) == "info"

        LogSettings.set_level(conn, "warning")
        assert LogSettings.get_level(conn) == "warning"

        with pytest.raises(ValueError):
            LogSettings.set_level(conn, "loud")

    def test_retention_defaults_to_15_and_validates(self, conn):
        assert LogSettings.get_retention_days(conn) == 15

        LogSettings.set_retention_days(conn, 3)
        assert LogSettings.get_retention_days(conn) == 3

        with pytest.raises(ValueError):
            LogSettings.set_retention_days(conn, 0)
