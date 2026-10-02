import logging
import sqlite3
from datetime import UTC, datetime, timedelta

import vethuq_core.db.integrity as integrity_module
from vethuq_core.db.integrity import IntegrityCheck
from vethuq_core.db.queries import Integrity as IntegrityQuery
from vethuq_core.db.queries import Settings as SettingsQuery
from vethuq_core.settings import DbSettings


def _clear_last_run_at(conn: sqlite3.Connection) -> None:
    # `Db.connect()` (the `conn` fixture) already runs the check once on a fresh
    # database, so the tests below clear its timestamp first to observe their
    # own first run as due, rather than skipped as too recent.
    conn.execute("DELETE FROM settings WHERE key = ?", (IntegrityCheck.LAST_RUN_AT_KEY,))
    conn.commit()


class TestRun:
    def test_passes_on_a_healthy_database(self, conn: sqlite3.Connection):
        result = IntegrityCheck.run(conn)

        assert result.ok is True
        assert result.errors == []

    def test_logs_success(self, conn: sqlite3.Connection, caplog):
        with caplog.at_level(logging.INFO, logger=integrity_module.__name__):
            IntegrityCheck.run(conn)

        assert any(record.levelno == logging.INFO for record in caplog.records)

    def test_records_last_run_timestamp(self, conn: sqlite3.Connection):
        _clear_last_run_at(conn)

        IntegrityCheck.run(conn)

        assert SettingsQuery.get_value(conn, IntegrityCheck.LAST_RUN_AT_KEY) is not None

    def test_reports_and_logs_specific_errors(self, conn: sqlite3.Connection, monkeypatch, caplog):
        monkeypatch.setattr(
            IntegrityQuery,
            "run_pragma",
            staticmethod(lambda _conn: ["row 3 missing from index x"]),
        )

        with caplog.at_level(logging.ERROR, logger=integrity_module.__name__):
            result = IntegrityCheck.run(conn)

        assert result.ok is False
        assert result.errors == ["row 3 missing from index x"]
        assert any(record.levelno == logging.ERROR for record in caplog.records)


class TestMaybeRun:
    def test_disabled_never_runs(self, conn: sqlite3.Connection, monkeypatch):
        DbSettings.set_integrity_check(conn, "disable")
        calls: list[None] = []

        def _fake_pragma(_conn: sqlite3.Connection) -> list[str]:
            calls.append(None)
            return ["ok"]

        monkeypatch.setattr(IntegrityQuery, "run_pragma", staticmethod(_fake_pragma))

        assert IntegrityCheck.maybe_run(conn) is None
        assert calls == []

    def test_enabled_runs_every_time(self, conn: sqlite3.Connection):
        DbSettings.set_integrity_check(conn, "enable")

        assert IntegrityCheck.maybe_run(conn) is not None
        assert IntegrityCheck.maybe_run(conn) is not None

    def test_auto_runs_once_then_skips_within_interval(self, conn: sqlite3.Connection):
        DbSettings.set_integrity_check(conn, "auto")
        DbSettings.set_integrity_check_interval_minutes(conn, 60)
        _clear_last_run_at(conn)

        first = IntegrityCheck.maybe_run(conn)
        second = IntegrityCheck.maybe_run(conn)

        assert first is not None
        assert second is None

    def test_auto_runs_again_once_interval_elapses(self, conn: sqlite3.Connection):
        DbSettings.set_integrity_check(conn, "auto")
        DbSettings.set_integrity_check_interval_minutes(conn, 60)
        _clear_last_run_at(conn)
        IntegrityCheck.maybe_run(conn)

        stale_timestamp = (datetime.now(UTC) - timedelta(minutes=61)).isoformat()
        SettingsQuery.upsert(conn, IntegrityCheck.LAST_RUN_AT_KEY, stale_timestamp)

        assert IntegrityCheck.maybe_run(conn) is not None
