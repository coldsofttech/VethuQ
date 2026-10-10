from __future__ import annotations

import pytest

import vethuq
from vethuq import errors


class TestSettings:
    @pytest.fixture
    def client(self, tmp_path):
        with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
            yield client

    def test_removed_retention_defaults_to_seven_days(self, client):
        assert client.settings.sources.get_removed_retention_minutes() == 7 * 24 * 60
        assert client.settings.sources.DEFAULT_REMOVED_RETENTION_MINUTES == 10080

    def test_set_and_get(self, client):
        client.settings.sources.set_removed_retention_minutes(60)

        assert client.settings.sources.get_removed_retention_minutes() == 60

    def test_the_value_is_kept_in_the_database(self, client):
        client.settings.sources.set_removed_retention_minutes(60)

        with vethuq.VethuQ(db_path=client.db_path) as other:
            assert other.settings.sources.get_removed_retention_minutes() == 60

    def test_reset(self, client):
        client.settings.sources.set_removed_retention_minutes(60)
        client.settings.sources.reset_removed_retention_minutes()

        assert client.settings.sources.get_removed_retention_minutes() == 10080

    def test_a_negative_value_is_rejected(self, client):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.sources.set_removed_retention_minutes(-1)

    def test_errors_are_settings_and_vethuq_errors(self, client):
        with pytest.raises(errors.SettingsError):
            client.settings.sources.set_removed_retention_minutes("x")
        with pytest.raises(errors.VethuQError):
            client.settings.sources.set_removed_retention_minutes(-1)

    def test_settings_object_is_reused(self, client):
        assert client.settings is client.settings
        assert client.settings.sources is client.settings.sources

    def test_close_then_use_again(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "vethuq.db")
        client.settings.sources.set_removed_retention_minutes(5)
        client.close()

        assert client.settings.sources.get_removed_retention_minutes() == 5
        client.close()


class TestLogSettings:
    @pytest.fixture
    def client(self, tmp_path):
        with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
            yield client

    def test_defaults(self, client):
        assert client.settings.logs.get_level() is vethuq.LogLevel.INFO
        assert client.settings.logs.get_retention_days() == 15
        assert client.settings.logs.DEFAULT_LEVEL is vethuq.LogLevel.INFO
        assert client.settings.logs.DEFAULT_RETENTION_DAYS == 15

    def test_set_and_get_the_level(self, client):
        client.settings.logs.set_level(vethuq.LogLevel.DEBUG)
        assert client.settings.logs.get_level() is vethuq.LogLevel.DEBUG

        client.settings.logs.set_level("error")
        assert client.settings.logs.get_level() is vethuq.LogLevel.ERROR

    def test_reset_the_level(self, client):
        client.settings.logs.set_level("error")
        client.settings.logs.reset_level()

        assert client.settings.logs.get_level() is vethuq.LogLevel.INFO

    def test_set_and_get_the_retention(self, client):
        client.settings.logs.set_retention_days(30)
        assert client.settings.logs.get_retention_days() == 30

        client.settings.logs.reset_retention_days()
        assert client.settings.logs.get_retention_days() == 15

    @pytest.mark.parametrize("call", ["set_level", "set_retention_days"])
    def test_bad_values_are_rejected(self, client, call):
        value = "loud" if call == "set_level" else 0
        with pytest.raises(errors.InvalidSettingValueError):
            getattr(client.settings.logs, call)(value)

    def test_a_rejected_value_leaves_the_setting_alone(self, client):
        client.settings.logs.set_retention_days(9)
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.logs.set_retention_days(-2)

        assert client.settings.logs.get_retention_days() == 9

    def test_settings_are_kept_in_the_database(self, client):
        client.settings.logs.set_level("warning")

        with vethuq.VethuQ(db_path=client.db_path) as other:
            assert other.settings.logs.get_level() is vethuq.LogLevel.WARNING

    def test_the_logs_settings_object_is_reused(self, client):
        assert client.settings.logs is client.settings.logs
