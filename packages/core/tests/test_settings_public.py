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
