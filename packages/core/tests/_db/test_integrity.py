from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from vethuq import errors
from vethuq._db import IntegrityCheckResult, _Database, _IntegrityCheck
from vethuq._logs import _DatabaseLog
from vethuq.enums import IntegrityCheckMode

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "db" / "vethuq.db"


@pytest.fixture
def healthy(db_path):
    """A real VethuQ database file, closed, with automatic checks off so nothing is recorded."""
    db_path.parent.mkdir(parents=True)
    _set(db_path, "db_integrity_check", "disable", create=True)
    database = _Database(db_path)
    with database.session():
        pass
    database.dispose()
    return db_path


def _set(db_path, key, value, create=False):
    with sqlite3.connect(db_path) as conn:
        if create:
            conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))


def _damage(db_path, table="sources"):
    """Wreck one table's root page so SQLite reports the file as damaged but still opens it."""
    with sqlite3.connect(db_path) as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        query = "SELECT rootpage FROM sqlite_master WHERE name = ?"
        root = conn.execute(query, (table,)).fetchone()[0]
    with open(db_path, "r+b") as handle:
        handle.seek((root - 1) * page_size)
        handle.write(b"\x00" * page_size)


def _result(ok=True, quick=False, ago=timedelta(0), errors=()):
    return IntegrityCheckResult(ok=ok, errors=tuple(errors), checked_at=NOW - ago, quick=quick)


class TestIntegrityCheckResult:
    def test_to_dict_and_json(self):
        result = _result(ok=False, errors=("bad page",), quick=True)

        assert result.to_dict() == {
            "ok": False,
            "errors": ["bad page"],
            "checked_at": "2026-10-01T12:00:00+00:00",
            "quick": True,
        }
        assert json.loads(result.to_json()) == result.to_dict()
        assert "\n" in result.to_json(indent=2)

    def test_round_trips_through_json(self):
        result = _result(ok=False, errors=("a", "b"), quick=True)

        assert IntegrityCheckResult.from_json(result.to_json()) == result

    @pytest.mark.parametrize(
        "text",
        [
            None,
            "",
            "not json",
            "[]",
            "3",
            "{}",
            '{"ok": "yes"}',
            '{"ok": true}',
            '{"ok": true, "checked_at": "never"}',
        ],
    )
    def test_anything_unreadable_is_none(self, text):
        assert IntegrityCheckResult.from_json(text) is None

    def test_a_time_without_a_zone_is_utc(self):
        text = '{"ok": true, "errors": [], "checked_at": "2026-10-01T12:00:00"}'

        assert IntegrityCheckResult.from_json(text).checked_at.tzinfo is UTC

    def test_damaged_error_lists_are_tolerated(self):
        text = '{"ok": false, "errors": "oops", "checked_at": "2026-10-01T12:00:00+00:00"}'

        assert IntegrityCheckResult.from_json(text).errors == ()

    def test_is_frozen(self):
        with pytest.raises(AttributeError):
            _result().ok = False


class TestRun:
    def test_a_healthy_database_passes(self, healthy):
        result = _IntegrityCheck.run(healthy, now=NOW)

        assert (result.ok, result.errors, result.quick) == (True, (), False)
        assert result.checked_at == NOW

    def test_a_quick_check_says_so(self, healthy):
        assert _IntegrityCheck.run(healthy, quick=True).quick is True

    def test_a_damaged_database_fails_with_sqlites_messages(self, healthy):
        _damage(healthy)

        result = _IntegrityCheck.run(healthy)

        assert result.ok is False and result.errors
        assert any("malformed" in message or "page" in message for message in result.errors)

    def test_the_default_time_is_now_in_utc(self, healthy):
        before = datetime.now(UTC)

        result = _IntegrityCheck.run(healthy)

        assert before <= result.checked_at <= datetime.now(UTC)

    def test_a_file_that_is_not_a_database_fails_instead_of_raising(self, db_path):
        db_path.parent.mkdir(parents=True)
        db_path.write_bytes(b"this is definitely not a sqlite database" * 50)

        result = _IntegrityCheck.run(db_path)

        assert result.ok is False and result.errors

    def test_the_result_is_saved_and_readable(self, healthy):
        result = _IntegrityCheck.run(healthy, now=NOW)

        assert _IntegrityCheck.status(healthy) == result

    def test_a_failure_is_saved_too(self, healthy):
        _damage(healthy)
        _IntegrityCheck.run(healthy, now=NOW)

        status = _IntegrityCheck.status(healthy)

        assert status.ok is False and status.errors

    def test_the_latest_result_replaces_the_one_before(self, healthy):
        _IntegrityCheck.run(healthy, quick=True, now=NOW)
        _IntegrityCheck.run(healthy, now=NOW + timedelta(hours=1))

        assert _IntegrityCheck.status(healthy).quick is False

    @staticmethod
    def _log_lines(db_path):
        return (db_path.parent.parent / "logs" / "database.log").read_text(encoding="utf-8")

    def test_success_and_failure_are_logged_to_the_database_log(self, healthy):
        _DatabaseLog.setup(healthy)
        _IntegrityCheck.run(healthy)
        _damage(healthy)
        _IntegrityCheck.run(healthy)

        lines = self._log_lines(healthy).splitlines()

        assert any(" INFO " in line and "integrity check passed" in line for line in lines)
        assert any(" ERROR " in line and "integrity check failed" in line for line in lines)

    def test_a_quick_check_is_logged_as_one(self, healthy):
        _DatabaseLog.setup(healthy)
        _IntegrityCheck.run(healthy, quick=True)

        assert "quick check passed" in self._log_lines(healthy)

    def test_a_result_that_cannot_be_saved_does_not_raise(self, db_path):
        db_path.parent.mkdir(parents=True)
        sqlite3.connect(db_path).close()  # a database with no settings table

        result = _IntegrityCheck.run(db_path)

        assert result.ok is True and _IntegrityCheck.status(db_path) is None

    def test_status_of_a_missing_database_is_none(self, db_path):
        assert _IntegrityCheck.status(db_path) is None


class TestMaybeRun:
    def test_disable_never_runs(self, healthy):
        _set(healthy, "db_integrity_check", "disable")

        assert _IntegrityCheck.maybe_run(healthy, NOW) is None
        assert _IntegrityCheck.status(healthy) is None

    def test_enable_runs_every_time(self, healthy):
        _set(healthy, "db_integrity_check", "enable")

        first = _IntegrityCheck.maybe_run(healthy, NOW)
        second = _IntegrityCheck.maybe_run(healthy, NOW + timedelta(seconds=1))

        assert first.ok and second.ok

    def test_auto_runs_the_first_time_then_waits_for_the_interval(self, healthy):
        _set(healthy, "db_integrity_check", "auto")

        assert _IntegrityCheck.maybe_run(healthy, NOW).ok is True
        assert _IntegrityCheck.maybe_run(healthy, NOW + timedelta(hours=23)) is None
        assert _IntegrityCheck.maybe_run(healthy, NOW + timedelta(hours=25)).ok is True

    def test_auto_uses_the_interval_setting(self, healthy):
        _set(healthy, "db_integrity_check", "auto")
        _set(healthy, "db_integrity_check_interval_minutes", 10)
        _IntegrityCheck.maybe_run(healthy, NOW)

        assert _IntegrityCheck.maybe_run(healthy, NOW + timedelta(minutes=9)) is None
        assert _IntegrityCheck.maybe_run(healthy, NOW + timedelta(minutes=11)) is not None

    def test_auto_checks_again_at_once_after_a_failure(self, healthy):
        _set(healthy, "db_integrity_check", "auto")
        _damage(healthy)
        assert _IntegrityCheck.maybe_run(healthy, NOW).ok is False

        again = _IntegrityCheck.maybe_run(healthy, NOW + timedelta(minutes=1))

        assert again is not None and again.ok is False

    def test_auto_does_not_count_a_quick_check_as_done(self, healthy):
        _set(healthy, "db_integrity_check", "auto")
        _IntegrityCheck.run(healthy, quick=True, now=NOW)

        result = _IntegrityCheck.maybe_run(healthy, NOW + timedelta(minutes=1))

        assert result is not None and result.quick is False

    @pytest.mark.parametrize("saved", ["sometimes", "", "ON"])
    def test_a_bad_mode_means_auto(self, healthy, saved):
        _set(healthy, "db_integrity_check", saved)

        assert _IntegrityCheck.read_mode(healthy) is IntegrityCheckMode.AUTO

    @pytest.mark.parametrize(
        ("saved", "expected"), [("30", 30), ("0", 1440), ("-5", 1440), ("x", 1440)]
    )
    def test_a_bad_interval_means_the_default(self, healthy, saved, expected):
        _set(healthy, "db_integrity_check_interval_minutes", saved)

        assert _IntegrityCheck.read_interval_minutes(healthy) == expected

    def test_without_settings_the_defaults_apply(self, db_path):
        assert _IntegrityCheck.read_mode(db_path) is IntegrityCheckMode.AUTO
        assert _IntegrityCheck.read_interval_minutes(db_path) == 1440


class TestOpeningTheDatabase:
    def test_a_healthy_database_opens_and_records_a_pass(self, db_path):
        database = _Database(db_path)

        with database.session():
            pass

        assert _IntegrityCheck.status(db_path).ok is True
        database.dispose()

    def test_disable_skips_the_check_on_open(self, healthy):
        database = _Database(healthy)

        with database.session():
            pass

        assert _IntegrityCheck.status(healthy) is None
        database.dispose()

    def test_a_damaged_database_is_refused_with_a_corrupt_database_error(self, healthy):
        _set(healthy, "db_integrity_check", "enable")
        _damage(healthy)
        database = _Database(healthy)

        with pytest.raises(errors.CorruptDatabaseError) as excinfo:
            with database.session():
                pass

        assert excinfo.value.exit_code == 12
        assert "failed its integrity check" in excinfo.value.message
        assert str(healthy) in excinfo.value.message
        assert "client.db.integrity_check()" in excinfo.value.hint

    def test_the_refusal_stays_until_the_database_is_disposed_without_checking_again(
        self, healthy, monkeypatch
    ):
        _set(healthy, "db_integrity_check", "enable")
        _damage(healthy)
        database = _Database(healthy)
        runs = []
        real = _IntegrityCheck.run
        monkeypatch.setattr(
            _IntegrityCheck,
            "run",
            staticmethod(lambda *a, **k: runs.append(1) or real(*a, **k)),
        )

        for _ in range(3):
            with pytest.raises(errors.CorruptDatabaseError):
                with database.session():
                    pass

        assert len(runs) == 1
        database.dispose()
        with pytest.raises(errors.CorruptDatabaseError):
            with database.session():
                pass
        assert len(runs) == 2

    def test_a_database_fixed_in_the_meantime_opens_after_dispose(self, healthy):
        _set(healthy, "db_integrity_check", "enable")
        original = healthy.read_bytes()
        _damage(healthy)
        database = _Database(healthy)
        with pytest.raises(errors.CorruptDatabaseError):
            with database.session():
                pass
        healthy.write_bytes(original)  # restored from a copy
        database.dispose()

        with database.session():
            pass
        database.dispose()

    def test_auto_checks_a_damaged_database_again_at_the_next_open(self, healthy):
        _set(healthy, "db_integrity_check", "auto")
        database = _Database(healthy)
        with database.session():
            pass  # passes, and is recorded as done for a day
        database.dispose()
        _damage(healthy)

        throttled = _Database(healthy)
        with throttled.session():
            pass  # inside the interval, so not checked: it opens
        throttled.dispose()
        _IntegrityCheck.run(healthy)  # ... but the next check finds it
        again = _Database(healthy)
        with pytest.raises(errors.CorruptDatabaseError):
            with again.session():
                pass

    def test_a_file_that_is_not_a_database_is_a_corrupt_database_error(self, db_path):
        db_path.parent.mkdir(parents=True)
        db_path.write_bytes(b"this is definitely not a sqlite database" * 50)
        database = _Database(db_path)

        with pytest.raises(errors.CorruptDatabaseError) as excinfo:
            with database.session():
                pass

        assert excinfo.value.exit_code == 12
        assert str(db_path) in excinfo.value.message
        assert "Restore a backup" in excinfo.value.hint

    def test_a_locked_database_is_not_reported_as_corrupt(self, db_path):
        locked = OperationalError("select 1", {}, sqlite3.OperationalError("database is locked"))

        assert _Database._corruption_error(locked, db_path) is None
        assert _Database._corruption_error(sqlite3.OperationalError("locked"), db_path) is None

    def test_a_plain_database_error_is_corruption(self, db_path):
        reason = sqlite3.DatabaseError("file is not a database")

        error = _Database._corruption_error(reason, db_path)

        assert isinstance(error, errors.CorruptDatabaseError)

    def test_on_open_runs_once_per_open_with_a_session(self, db_path):
        calls = []
        database = _Database(db_path, on_open=lambda session: calls.append(session))

        with database.session():
            pass
        with database.session():
            pass

        assert len(calls) == 1
        database.dispose()
        with database.session():
            pass
        assert len(calls) == 2
        database.dispose()

    def test_on_open_failing_is_logged_and_never_raised(self, db_path):
        def boom(session):
            raise RuntimeError("maintenance exploded")

        database = _Database(db_path, on_open=boom)

        with database.session():
            pass

        text = (db_path.parent.parent / "logs" / "database.log").read_text(encoding="utf-8")
        assert "Maintenance on opening the database failed" in text
        assert "maintenance exploded" in text
        database.dispose()

    def test_on_open_does_not_run_when_the_database_is_refused(self, healthy):
        _set(healthy, "db_integrity_check", "enable")
        _damage(healthy)
        calls = []
        database = _Database(healthy, on_open=lambda session: calls.append(1))

        with pytest.raises(errors.CorruptDatabaseError):
            with database.session():
                pass

        assert calls == []
