from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

import vethuq
from vethuq import errors
from vethuq._db import _Source


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


def _damage(db_path, table="sources"):
    with sqlite3.connect(db_path) as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        query = "SELECT rootpage FROM sqlite_master WHERE name = ?"
        root = conn.execute(query, (table,)).fetchone()[0]
    with open(db_path, "r+b") as handle:
        handle.seek((root - 1) * page_size)
        handle.write(b"\x00" * page_size)


class TestDbAccess:
    def test_is_on_the_client_and_a_module(self, client):
        assert isinstance(client.db, vethuq.db.Db)
        assert client.db is client.db

    def test_the_types_live_in_vethuq_db(self):
        for name in ("Db", "IntegrityCheckResult", "IntegrityCheckMode"):
            assert name in vethuq.db.__all__ and not hasattr(vethuq, name)

    def test_the_enum_is_the_shared_one(self):
        assert vethuq.db.IntegrityCheckMode is vethuq.enums.IntegrityCheckMode

    def test_no_check_has_run_before_the_database_exists(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db")

        assert client.db.integrity_status() is None
        assert not (tmp_path / "db").exists()


class TestIntegrityCheck:
    def test_a_healthy_database_passes(self, client):
        result = client.db.integrity_check()

        assert isinstance(result, vethuq.db.IntegrityCheckResult)
        assert (result.ok, result.errors, result.quick) == (True, (), False)
        assert result.checked_at.tzinfo is UTC

    def test_a_quick_check(self, client):
        result = client.db.integrity_check(quick=True)

        assert result.ok is True and result.quick is True

    def test_it_creates_the_database_when_there_is_none(self, client, tmp_path):
        assert not (tmp_path / "db" / "vethuq.db").exists()

        assert client.db.integrity_check().ok is True
        assert (tmp_path / "db" / "vethuq.db").is_file()

    def test_the_result_is_saved_and_can_be_read_again(self, client):
        result = client.db.integrity_check()

        assert client.db.integrity_status() == result

    def test_using_the_database_runs_the_automatic_check_and_records_it(self, client):
        client.sources.list()

        status = client.db.integrity_status()

        assert status is not None and status.ok is True

    def test_the_result_has_json(self, client):
        data = json.loads(client.db.integrity_check().to_json())

        assert data["ok"] is True and data["errors"] == [] and data["quick"] is False

    def test_a_damaged_database_gives_a_failed_result_instead_of_raising(self, client, tmp_path):
        client.db.integrity_check()
        client.close()
        _damage(tmp_path / "db" / "vethuq.db")

        result = client.db.integrity_check()

        assert result.ok is False and result.errors
        assert client.db.integrity_status().ok is False

    def test_it_is_written_to_the_database_log(self, client):
        client.sources.list()  # opens the database, which sets up the log
        client.db.integrity_check()

        messages = [e.message for e in client.logs.database.read()]

        assert any("integrity check passed" in m for m in messages)


class TestWhenTheDatabaseIsDamaged:
    @pytest.fixture
    def damaged(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        with vethuq.VethuQ(db_path=db_path) as client:
            client.settings.database.set_integrity_check("enable")
        _damage(db_path)
        return db_path

    def test_opening_it_raises_a_corrupt_database_error(self, damaged):
        with vethuq.VethuQ(db_path=damaged) as client:
            with pytest.raises(errors.CorruptDatabaseError) as excinfo:
                client.sources.list()

        assert excinfo.value.exit_code == 12
        assert "failed its integrity check" in excinfo.value.message

    def test_it_is_a_vethuq_error_and_a_startup_style_failure_with_a_hint(self, damaged):
        with vethuq.VethuQ(db_path=damaged) as client:
            with pytest.raises(errors.VethuQError) as excinfo:
                client.languages.list_all()

        assert "client.db.integrity_check()" in excinfo.value.hint

    def test_the_check_can_still_be_run_and_read_on_the_damaged_database(self, damaged):
        with vethuq.VethuQ(db_path=damaged) as client:
            with pytest.raises(errors.CorruptDatabaseError):
                client.sources.list()

            result = client.db.integrity_check()

            assert result.ok is False
            assert client.db.integrity_status().ok is False

    def test_logs_and_version_still_work(self, damaged):
        with vethuq.VethuQ(db_path=damaged) as client:
            with pytest.raises(errors.CorruptDatabaseError):
                client.sources.list()

            assert client.version.vethuq == vethuq.APP_VERSION
            assert any("failed" in e.message for e in client.logs.database.read(level="error"))

    def test_with_the_automatic_check_disabled_it_opens_and_only_a_manual_check_finds_it(
        self, tmp_path
    ):
        db_path = tmp_path / "db" / "vethuq.db"
        with vethuq.VethuQ(db_path=db_path) as client:
            client.settings.database.set_integrity_check(vethuq.db.IntegrityCheckMode.DISABLE)
        _damage(db_path)

        with vethuq.VethuQ(db_path=db_path) as client:
            assert client.languages.list_all()  # opens: nothing checked
            assert client.db.integrity_check().ok is False  # ... but the manual check finds it

    def test_a_file_that_is_not_a_database_is_a_corrupt_database_error(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        db_path.parent.mkdir()
        db_path.write_bytes(b"this is definitely not a sqlite database" * 50)

        with vethuq.VethuQ(db_path=db_path) as client:
            with pytest.raises(errors.CorruptDatabaseError) as excinfo:
                client.sources.list()
            assert client.db.integrity_check().ok is False

        assert "damaged or isn't a database" in excinfo.value.message


class TestDatabaseSettings:
    def test_defaults(self, client):
        settings = client.settings.database

        assert settings.get_integrity_check() is vethuq.db.IntegrityCheckMode.AUTO
        assert settings.get_integrity_check_interval_minutes() == 1440
        assert settings.DEFAULT_INTEGRITY_CHECK is vethuq.db.IntegrityCheckMode.AUTO
        assert settings.DEFAULT_INTEGRITY_CHECK_INTERVAL_MINUTES == 1440

    @pytest.mark.parametrize(
        "mode", ["enable", "disable", "auto", vethuq.enums.IntegrityCheckMode.ENABLE]
    )
    def test_set_the_mode(self, client, mode):
        client.settings.database.set_integrity_check(mode)

        expected = vethuq.db.IntegrityCheckMode(mode)

        assert client.settings.database.get_integrity_check() is expected

    def test_reset_the_mode(self, client):
        client.settings.database.set_integrity_check("disable")
        client.settings.database.reset_integrity_check()

        assert client.settings.database.get_integrity_check() is vethuq.db.IntegrityCheckMode.AUTO

    def test_set_and_reset_the_interval(self, client):
        client.settings.database.set_integrity_check_interval_minutes(60)
        assert client.settings.database.get_integrity_check_interval_minutes() == 60

        client.settings.database.reset_integrity_check_interval_minutes()
        assert client.settings.database.get_integrity_check_interval_minutes() == 1440

    @pytest.mark.parametrize("mode", ["sometimes", "", None, 3])
    def test_a_bad_mode_is_rejected_with_the_options(self, client, mode):
        with pytest.raises(errors.InvalidSettingValueError) as excinfo:
            client.settings.database.set_integrity_check(mode)

        assert "auto, enable, disable" in excinfo.value.hint

    @pytest.mark.parametrize("minutes", [0, -1, 1.5, "60", None, True])
    def test_a_bad_interval_is_rejected(self, client, minutes):
        with pytest.raises(errors.InvalidSettingValueError) as excinfo:
            client.settings.database.set_integrity_check_interval_minutes(minutes)

        assert "ENABLE" in excinfo.value.hint

    def test_a_rejected_value_leaves_the_setting_alone(self, client):
        client.settings.database.set_integrity_check_interval_minutes(90)
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.database.set_integrity_check_interval_minutes(0)

        assert client.settings.database.get_integrity_check_interval_minutes() == 90

    def test_the_settings_are_kept_in_the_database(self, client):
        client.settings.database.set_integrity_check("enable")

        with vethuq.VethuQ(db_path=client.db_path) as other:
            mode = other.settings.database.get_integrity_check()

        assert mode is vethuq.db.IntegrityCheckMode.ENABLE

    def test_disable_stops_the_automatic_check_at_the_next_open(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        with vethuq.VethuQ(db_path=db_path) as first:
            first.settings.database.set_integrity_check("disable")
            first.close()
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM settings WHERE key = 'integrity_check_last_result'")

        with vethuq.VethuQ(db_path=db_path) as second:
            second.sources.list()

            assert second.db.integrity_status() is None

    def test_the_settings_object_is_reused(self, client):
        assert client.settings.database is client.settings.database


class TestMaintenanceOnOpen:
    def _remove(self, client, source_id, days_ago):
        client.sources.remove(source_id)
        with client._db().session() as session:
            session.get(_Source, source_id).removed_at = (
                datetime.now(UTC) - timedelta(days=days_ago)
            ).isoformat()

    def test_sources_removed_longer_ago_than_the_retention_are_purged_when_opened(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        (tmp_path / "old").mkdir()
        (tmp_path / "recent").mkdir()
        with vethuq.VethuQ(db_path=db_path) as client:
            client.sources.create(tmp_path / "old")
            client.sources.create(tmp_path / "recent")
            self._remove(client, 1, days_ago=8)
            self._remove(client, 2, days_ago=2)

        with vethuq.VethuQ(db_path=db_path) as client:
            ids = [s.id for s in client.sources.list(include_removed=True)]

        assert ids == [2]

    def test_it_uses_the_retention_setting(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        (tmp_path / "docs").mkdir()
        with vethuq.VethuQ(db_path=db_path) as client:
            client.sources.create(tmp_path / "docs")
            self._remove(client, 1, days_ago=2)
            client.settings.sources.set_removed_retention_minutes(24 * 60)

        with vethuq.VethuQ(db_path=db_path) as client:
            assert client.sources.list(include_removed=True) == []

    def test_active_sources_are_never_purged_on_open(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        (tmp_path / "docs").mkdir()
        with vethuq.VethuQ(db_path=db_path) as client:
            client.sources.create(tmp_path / "docs")
            client.settings.sources.set_removed_retention_minutes(0)

        with vethuq.VethuQ(db_path=db_path) as client:
            assert [s.id for s in client.sources.list()] == [1]

    def test_the_purge_is_logged(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        (tmp_path / "docs").mkdir()
        with vethuq.VethuQ(db_path=db_path) as client:
            client.sources.create(tmp_path / "docs")
            self._remove(client, 1, days_ago=30)

        with vethuq.VethuQ(db_path=db_path) as client:
            client.sources.list()
            messages = [e.message for e in client.logs.database.read()]

        assert any(m.startswith("Cleanup (retention): purged source id=1") for m in messages)
