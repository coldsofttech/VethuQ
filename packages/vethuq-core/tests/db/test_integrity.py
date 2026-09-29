import logging
import sqlite3
from datetime import UTC, datetime, timedelta

import vethuq_core.db.integrity as integrity_module
from vethuq_core.db.integrity import IntegrityCheck
from vethuq_core.settings import DbSettings
from vethuq_core.storage import Storage
from vethuq_core.storage.sqlite import SqliteStorage


def _clear_last_run_at(conn: sqlite3.Connection) -> None:
    # `Db.connect()` (the `conn` fixture) already runs the check once on a fresh
    # database, so the tests below clear its timestamp first to observe their
    # own first run as due, rather than skipped as too recent.
    conn.execute("DELETE FROM settings WHERE key = ?", (IntegrityCheck.LAST_RUN_AT_KEY,))
    conn.commit()


class TestRun:
    def test_passes_on_a_healthy_database(self, storage: Storage):
        result = IntegrityCheck.run(storage)

        assert result.ok is True
        assert result.errors == []

    def test_logs_success(self, storage: Storage, caplog):
        with caplog.at_level(logging.INFO, logger=integrity_module.__name__):
            IntegrityCheck.run(storage)

        assert any(record.levelno == logging.INFO for record in caplog.records)

    def test_records_last_run_timestamp(self, conn: sqlite3.Connection, storage: Storage):
        _clear_last_run_at(conn)

        IntegrityCheck.run(storage)

        assert storage.get_setting_value(IntegrityCheck.LAST_RUN_AT_KEY) is not None

    def test_reports_and_logs_specific_errors(self, storage: Storage, monkeypatch, caplog):
        monkeypatch.setattr(
            SqliteStorage,
            "run_integrity_check_pragma",
            lambda _self: ["row 3 missing from index x"],
        )

        with caplog.at_level(logging.ERROR, logger=integrity_module.__name__):
            result = IntegrityCheck.run(storage)

        assert result.ok is False
        assert result.errors == ["row 3 missing from index x"]
        assert any(record.levelno == logging.ERROR for record in caplog.records)


class TestMaybeRun:
    def test_disabled_never_runs(self, storage: Storage, monkeypatch):
        DbSettings.set_integrity_check(storage, "disable")
        calls: list[None] = []

        def _fake_pragma(_self) -> list[str]:
            calls.append(None)
            return ["ok"]

        monkeypatch.setattr(SqliteStorage, "run_integrity_check_pragma", _fake_pragma)

        assert IntegrityCheck.maybe_run(storage) is None
        assert calls == []

    def test_enabled_runs_every_time(self, storage: Storage):
        DbSettings.set_integrity_check(storage, "enable")

        assert IntegrityCheck.maybe_run(storage) is not None
        assert IntegrityCheck.maybe_run(storage) is not None

    def test_auto_runs_once_then_skips_within_interval(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        DbSettings.set_integrity_check(storage, "auto")
        DbSettings.set_integrity_check_interval_minutes(storage, 60)
        _clear_last_run_at(conn)

        first = IntegrityCheck.maybe_run(storage)
        second = IntegrityCheck.maybe_run(storage)

        assert first is not None
        assert second is None

    def test_auto_runs_again_once_interval_elapses(
        self, conn: sqlite3.Connection, storage: Storage
    ):
        DbSettings.set_integrity_check(storage, "auto")
        DbSettings.set_integrity_check_interval_minutes(storage, 60)
        _clear_last_run_at(conn)
        IntegrityCheck.maybe_run(storage)

        stale_timestamp = (datetime.now(UTC) - timedelta(minutes=61)).isoformat()
        storage.upsert_setting(IntegrityCheck.LAST_RUN_AT_KEY, stale_timestamp)

        assert IntegrityCheck.maybe_run(storage) is not None
