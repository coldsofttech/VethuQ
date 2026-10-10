from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

import pytest

from vethuq import errors
from vethuq._logs import (
    _CliLog,
    _DatabaseLog,
    _Entry,
    _IndexLog,
    _Log,
    _Logs,
    _SafeRotatingFileHandler,
    _UiLog,
)
from vethuq.enums import LogComponent, LogLevel, SortOrder


def _line(level: str, message: str, second: int = 0, minute: int = 0) -> str:
    stamp = f"2026-10-01 10:{minute:02d}:{second:02d},000"
    return f"{stamp} {level} [MainThread] vethuq.index: {message}"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "db" / "vethuq.db"


def _write(db_path, text, suffix="", log=_IndexLog):
    logs = db_path.parent.parent / "logs"
    logs.mkdir(exist_ok=True)
    (logs / f"{log.FILENAME}{suffix}").write_text(text, encoding="utf-8")


def _settings(db_path, **values):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        for key, value in values.items():
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))


class TestEntry:
    def test_parses_a_line(self):
        entry = _Entry.parse(_line("WARNING", "disk almost full: 91%"))

        assert entry.timestamp == datetime(2026, 10, 1, 10, 0, 0)
        assert entry.level is LogLevel.WARNING
        assert (entry.thread, entry.logger) == ("MainThread", "vethuq.index")
        assert entry.message == "disk almost full: 91%"

    def test_keeps_a_traceback_in_the_message(self):
        raw = _line("ERROR", "boom") + "\nTraceback (most recent call last):\n  File x\nValueError"

        entry = _Entry.parse(raw)

        assert entry.message.startswith("boom\nTraceback")
        assert entry.raw == raw

    def test_milliseconds_are_read(self):
        entry = _Entry.parse("2026-10-01 10:00:00,250 INFO [T] vethuq.cli: x")

        assert entry.timestamp.microsecond == 250_000

    def test_a_thread_name_with_spaces_is_read(self):
        entry = _Entry.parse("2026-10-01 10:00:00,000 INFO [ThreadPoolExecutor-0_1] vethuq.cli: m")

        assert entry.thread == "ThreadPoolExecutor-0_1"

    def test_critical_counts_as_error(self):
        assert _Entry.parse(_line("CRITICAL", "x")).level is LogLevel.ERROR

    def test_an_unknown_level_has_no_level(self):
        assert _Entry.parse(_line("NOTICE", "x")).level is None

    def test_text_in_another_format_is_kept_as_it_is(self):
        entry = _Entry.parse("something else")

        assert (entry.timestamp, entry.level, entry.logger) == (None, None, None)
        assert entry.message == entry.raw == "something else"

    def test_group_keeps_tracebacks_with_their_entry(self):
        lines = [
            _line("INFO", "a"),
            _line("ERROR", "b"),
            "Traceback",
            "  File x",
            _line("INFO", "c"),
        ]

        records = list(_Entry.group(lines))

        assert len(records) == 3 and records[1].splitlines()[1:] == ["Traceback", "  File x"]

    def test_group_of_nothing_is_nothing(self):
        assert list(_Entry.group([])) == []

    @pytest.mark.parametrize(
        ("level", "minimum", "expected"),
        [
            ("DEBUG", LogLevel.INFO, False),
            ("INFO", LogLevel.INFO, True),
            ("ERROR", LogLevel.WARNING, True),
            ("WARNING", LogLevel.ERROR, False),
            ("INFO", None, True),
        ],
    )
    def test_passes_the_level(self, level, minimum, expected):
        assert _Entry.parse(_line(level, "x")).passes(minimum, None) is expected

    def test_an_entry_of_unknown_format_always_passes_the_level(self):
        assert _Entry.parse("plain").passes(LogLevel.ERROR, None) is True

    def test_contains_ignores_case(self):
        entry = _Entry.parse(_line("INFO", "Source Created"))

        assert entry.passes(None, "source created") is True
        assert entry.passes(None, "missing") is False

    def test_contains_searches_only_the_message_not_the_level_thread_or_logger(self):
        entry = _Entry.parse(_line("INFO", "hello"))

        for text in ("info", "mainthread", "vethuq.index", "2026"):
            assert entry.passes(None, text) is False

    def test_contains_also_searches_the_traceback(self):
        entry = _Entry.parse(_line("ERROR", "boom") + "\nValueError: bad")

        assert entry.passes(None, "valueerror") is True


class TestComponents:
    def test_every_component_has_a_log_with_its_own_file(self):
        assert {log.COMPONENT for log in _Logs.ALL.values()} == set(LogComponent)
        assert {log.FILENAME for log in _Logs.ALL.values()} == {
            "database.log",
            "index.log",
            "ui.log",
            "cli.log",
            "policy.log",
        }

    def test_the_components_share_one_base(self):
        for log in (_DatabaseLog, _IndexLog, _UiLog, _CliLog):
            assert issubclass(log, _Log) and log.DESCRIPTION

    def test_each_has_its_own_logger(self):
        assert _CliLog.logger().name == "vethuq.cli"
        assert _DatabaseLog.logger() is logging.getLogger("vethuq.database")

    def test_get_accepts_an_enum_or_a_name(self):
        assert _Logs.get(LogComponent.UI) is _UiLog
        assert _Logs.get("ui") is _UiLog

    def test_get_rejects_an_unknown_component(self):
        with pytest.raises(errors.InvalidLogRequestError) as excinfo:
            _Logs.get("nope")

        assert "nope" in excinfo.value.message and "database" in excinfo.value.hint
        assert excinfo.value.exit_code == 42


class TestFilesAndDays:
    def test_file_path_is_in_the_logs_folder_next_to_the_db_folder(self, tmp_path, db_path):
        assert _CliLog.file_path(db_path) == tmp_path / "logs" / "cli.log"

    def test_a_past_day_is_the_rotated_file(self, tmp_path, db_path):
        assert _CliLog.file_path(db_path, date(2026, 10, 1)) == (
            tmp_path / "logs" / "cli.log.2026-10-01"
        )

    def test_today_is_the_plain_file(self, tmp_path, db_path):
        assert _CliLog.file_path(db_path, date.today()) == tmp_path / "logs" / "cli.log"

    def test_asking_for_a_path_creates_nothing(self, tmp_path, db_path):
        _CliLog.file_path(db_path)
        _CliLog.days(db_path)

        assert not (tmp_path / "logs").exists()

    def test_days_lists_rotated_days_and_today(self, db_path):
        _write(db_path, "x", log=_CliLog)
        _write(db_path, "x", ".2026-10-02", log=_CliLog)
        _write(db_path, "x", ".2026-10-01", log=_CliLog)
        _write(db_path, "x", ".notadate", log=_CliLog)

        assert _CliLog.days(db_path) == [date(2026, 10, 1), date(2026, 10, 2), date.today()]

    def test_days_without_a_log_is_empty(self, db_path):
        assert _CliLog.days(db_path) == []


class TestSetup:
    def test_writes_to_the_component_file(self, tmp_path, db_path):
        logger = _CliLog.setup(db_path)

        logger.info("hello")
        _CliLog.detach()

        text = (tmp_path / "logs" / "cli.log").read_text(encoding="utf-8")
        assert "INFO [MainThread] vethuq.cli: hello" in text

    def test_other_components_are_not_written(self, tmp_path, db_path):
        _CliLog.setup(db_path).info("hello")
        _CliLog.detach()

        assert not (tmp_path / "logs" / "ui.log").exists()

    def test_the_default_level_is_info_and_loggers_do_not_propagate(self, db_path):
        logger = _CliLog.setup(db_path)

        assert logger.level == logging.INFO
        assert logger.propagate is False

    def test_debug_entries_are_dropped_at_the_default_level(self, tmp_path, db_path):
        logger = _CliLog.setup(db_path)
        logger.debug("noise")
        logger.info("signal")
        _CliLog.detach()

        text = (tmp_path / "logs" / "cli.log").read_text(encoding="utf-8")
        assert "signal" in text and "noise" not in text

    def test_the_level_setting_is_used(self, db_path):
        _settings(db_path, log_level="error")

        assert _CliLog.setup(db_path).level == logging.ERROR

    def test_an_invalid_saved_level_falls_back_to_the_default(self, db_path):
        _settings(db_path, log_level="loud")

        assert _CliLog.read_level(db_path) is LogLevel.INFO

    @pytest.mark.parametrize(("saved", "expected"), [("9", 9), ("0", 15), ("-3", 15), ("x", 15)])
    def test_retention_setting_with_a_default_for_bad_values(self, db_path, saved, expected):
        _settings(db_path, log_retention_days=saved)

        assert _CliLog.read_retention_days(db_path) == expected

    def test_retention_defaults_to_fifteen_without_a_database(self, db_path):
        assert _CliLog.read_retention_days(db_path) == 15
        assert _CliLog.read_level(db_path) is LogLevel.INFO

    def test_the_handler_rotates_daily_and_keeps_the_retention(self, db_path):
        _settings(db_path, log_retention_days=9)
        logger = _UiLog.setup(db_path)

        (handler,) = logger.handlers
        assert isinstance(handler, TimedRotatingFileHandler)
        assert isinstance(handler, _SafeRotatingFileHandler)
        assert handler.when == "MIDNIGHT" and handler.backupCount == 9

    def test_setting_up_twice_keeps_one_handler(self, db_path):
        _CliLog.setup(db_path)
        _CliLog.setup(db_path)

        assert len(_CliLog.logger().handlers) == 1

    def test_a_different_database_moves_the_log_file(self, tmp_path):
        first, second = tmp_path / "a" / "db" / "vethuq.db", tmp_path / "b" / "db" / "vethuq.db"
        _CliLog.setup(first).info("one")
        _CliLog.setup(second).info("two")
        _CliLog.detach()

        assert "one" in (tmp_path / "a" / "logs" / "cli.log").read_text()
        assert "two" in (tmp_path / "b" / "logs" / "cli.log").read_text()
        assert "two" not in (tmp_path / "a" / "logs" / "cli.log").read_text()

    def test_an_unwritable_folder_is_survived(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("x")

        logger = _CliLog.setup(blocker / "db" / "vethuq.db")
        logger.info("still fine")

        assert not any(isinstance(h, _SafeRotatingFileHandler) for h in logger.handlers)

    def test_setup_prunes_old_files_past_the_retention(self, tmp_path, db_path):
        _settings(db_path, log_retention_days=5)
        old = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        _write(db_path, "x", f".{old}", log=_CliLog)

        _CliLog.setup(db_path)

        assert not (tmp_path / "logs" / f"cli.log.{old}").exists()

    def test_prune_old_deletes_only_files_past_retention(self, tmp_path):
        log_file = tmp_path / "index.log"
        log_file.write_text("today")

        def dated(days_ago):
            day = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            path = tmp_path / f"index.log.{day}"
            path.write_text("x")
            return path

        recent, boundary, old = dated(3), dated(5), dated(6)
        unrelated = tmp_path / "index.log.notadate"
        unrelated.write_text("x")

        _Log.prune_old(log_file, 5)

        assert log_file.exists() and recent.exists() and boundary.exists()
        assert not old.exists() and unrelated.exists()

    def test_detach_releases_the_file(self, db_path):
        _CliLog.setup(db_path)

        _CliLog.detach()

        assert _CliLog.logger().handlers == []


class TestReconfigure:
    def test_a_new_level_applies_to_the_running_logger(self, db_path):
        logger = _CliLog.setup(db_path)
        _settings(db_path, log_level="warning")

        _CliLog.reconfigure(db_path)

        assert logger.level == logging.WARNING

    def test_a_new_retention_applies_to_the_handler(self, db_path):
        logger = _CliLog.setup(db_path)
        _settings(db_path, log_retention_days=3)

        _CliLog.reconfigure(db_path)

        assert logger.handlers[0].backupCount == 3

    def test_a_shorter_retention_prunes_at_once(self, tmp_path, db_path):
        _CliLog.setup(db_path)
        old = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
        _write(db_path, "x", f".{old}", log=_CliLog)
        _settings(db_path, log_retention_days=2)

        _CliLog.reconfigure(db_path)

        assert not (tmp_path / "logs" / f"cli.log.{old}").exists()

    def test_a_logger_writing_elsewhere_is_left_alone(self, tmp_path, db_path):
        logger = _CliLog.setup(tmp_path / "other" / "db" / "vethuq.db")
        _settings(db_path, log_level="error")

        _CliLog.reconfigure(db_path)

        assert logger.level == logging.INFO

    def test_reconfiguring_without_a_handler_is_harmless(self, db_path):
        _CliLog.reconfigure(db_path)
        _Logs.reconfigure(db_path)


class TestReading:
    @pytest.fixture
    def entries(self, db_path):
        text = "\n".join(
            [
                _line("INFO", "start", 0),
                _line("DEBUG", "detail", 1),
                _line("WARNING", "retry file one", 2),
                _line("ERROR", "failed", 3),
                "Traceback (most recent call last):",
                "ValueError: bad value",
                _line("INFO", "done", 4),
            ]
        )
        _write(db_path, text + "\n")
        return db_path

    def test_read_returns_every_entry_oldest_first(self, entries):
        result = _IndexLog.read(entries)

        assert [e.message.splitlines()[0] for e in result] == [
            "start",
            "detail",
            "retry file one",
            "failed",
            "done",
        ]

    def test_a_traceback_stays_with_its_entry(self, entries):
        failed = next(e for e in _IndexLog.read(entries) if e.message.startswith("failed"))

        assert "ValueError: bad value" in failed.message

    def test_newest_first(self, entries):
        result = _IndexLog.read(entries, order=SortOrder.DESC)

        assert [e.message for e in result][0] == "done"
        assert [e.timestamp for e in result] == sorted([e.timestamp for e in result], reverse=True)

    def test_order_accepts_a_string(self, entries):
        assert _IndexLog.read(entries, order="desc")[0].message == "done"

    def test_filter_by_minimum_level(self, entries):
        levels = [e.level for e in _IndexLog.read(entries, level=LogLevel.WARNING)]

        assert levels == [LogLevel.WARNING, LogLevel.ERROR]

    def test_level_accepts_a_string(self, entries):
        assert len(_IndexLog.read(entries, level="error")) == 1

    def test_filter_by_text(self, entries):
        result = _IndexLog.read(entries, contains="FILE ONE")

        assert [e.level for e in result] == [LogLevel.WARNING]

    def test_filters_combine_with_sorting(self, entries):
        result = _IndexLog.read(entries, level="info", contains="d", order="desc")

        assert [e.message.splitlines()[0] for e in result] == ["done", "failed"]

    def test_tail_returns_the_last_entries_oldest_first(self, entries):
        result = _IndexLog.tail(entries, lines=2)

        assert [e.message.splitlines()[0] for e in result] == ["failed", "done"]

    def test_tail_newest_first(self, entries):
        assert [e.message for e in _IndexLog.tail(entries, lines=2, order="desc")][0] == "done"

    def test_tail_applies_the_filters_before_counting(self, entries):
        result = _IndexLog.tail(entries, lines=1, level="warning")

        assert result[0].message.startswith("failed")

    def test_tail_defaults_to_forty_entries(self, db_path):
        _write(db_path, "\n".join(_line("INFO", f"m{i}", i % 60, i // 60) for i in range(100)))

        assert len(_IndexLog.tail(db_path)) == 40
        assert _IndexLog.tail(db_path)[-1].message == "m99"

    def test_reads_a_rotated_day(self, db_path):
        _write(db_path, _line("INFO", "yesterday"), ".2026-09-30")

        assert [e.message for e in _IndexLog.read(db_path, day=date(2026, 9, 30))] == ["yesterday"]
        assert [e.message for e in _IndexLog.tail(db_path, day="2026-09-30")] == ["yesterday"]

    def test_a_missing_log_is_reported(self, db_path):
        with pytest.raises(errors.LogNotFoundError) as excinfo:
            _IndexLog.tail(db_path)

        assert "index" in excinfo.value.message and "list()" in excinfo.value.hint
        assert excinfo.value.exit_code == 41

    def test_a_missing_day_is_reported(self, entries):
        with pytest.raises(errors.LogNotFoundError):
            _IndexLog.read(entries, day="2020-01-01")

    @pytest.mark.parametrize("lines", [0, -1, 1.5, "3", True, None])
    def test_bad_line_counts_are_rejected(self, entries, lines):
        with pytest.raises(errors.InvalidLogRequestError) as excinfo:
            _IndexLog.tail(entries, lines=lines)

        assert excinfo.value.exit_code == 42 and "lines" in excinfo.value.message

    @pytest.mark.parametrize(
        ("kwargs", "word"),
        [
            ({"level": "loud"}, "level"),
            ({"order": "sideways"}, "order"),
            ({"day": "10/01/2026"}, "day"),
            ({"day": 5}, "day"),
        ],
    )
    def test_bad_arguments_are_rejected(self, entries, kwargs, word):
        with pytest.raises(errors.InvalidLogRequestError) as excinfo:
            _IndexLog.read(entries, **kwargs)

        assert word in excinfo.value.message

    def test_a_datetime_day_is_read_as_its_date(self, db_path):
        _write(db_path, _line("INFO", "x"), ".2026-09-30")

        assert len(_IndexLog.read(db_path, day=datetime(2026, 9, 30, 15, 0))) == 1

    def test_an_empty_file_has_no_entries(self, db_path):
        _write(db_path, "")

        assert _IndexLog.read(db_path) == []

    def test_a_non_utf8_byte_does_not_break_reading(self, db_path):
        logs = db_path.parent.parent / "logs"
        logs.mkdir()
        (logs / "index.log").write_bytes(_line("INFO", "caf").encode() + b"\xff\n")

        assert len(_IndexLog.read(db_path)) == 1


class TestFollow:
    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        monkeypatch.setattr(_Log, "FOLLOW_POLL_SECONDS", 0)

    @staticmethod
    def _follow(db_path, appended, **kwargs):
        """Follow while `appended` text is written to the file during the first poll."""
        calls = []

        def stop():
            calls.append(1)
            if len(calls) == 1:
                with open(db_path.parent.parent / "logs" / "index.log", "a", encoding="utf-8") as f:
                    f.write(appended)
            return len(calls) > 2

        return list(_IndexLog.follow(db_path, stop=stop, **kwargs))

    def test_yields_only_entries_written_after_it_starts(self, db_path):
        _write(db_path, _line("INFO", "old") + "\n")

        new = _line("INFO", "new one") + "\n" + _line("INFO", "new two") + "\n"

        result = self._follow(db_path, new)

        assert [e.message for e in result] == ["new one", "new two"]

    def test_filters_apply(self, db_path):
        _write(db_path, "")
        text = _line("INFO", "quiet") + "\n" + _line("ERROR", "loud") + "\n"

        assert [e.message for e in self._follow(db_path, text, level="error")] == ["loud"]
        assert [e.message for e in self._follow(db_path, text, contains="QUIET")][:1] == ["quiet"]

    def test_a_traceback_stays_with_its_entry(self, db_path):
        _write(db_path, "")

        result = self._follow(db_path, _line("ERROR", "boom") + "\nTraceback\nValueError\n")

        assert len(result) == 1 and "ValueError" in result[0].message

    def test_waits_for_a_log_that_does_not_exist_yet(self, db_path):
        (db_path.parent.parent / "logs").mkdir(parents=True)

        result = self._follow(db_path, _line("INFO", "first") + "\n")

        assert [e.message for e in result] == ["first"]

    def test_survives_the_file_being_replaced_by_a_shorter_one(self, db_path):
        _write(db_path, _line("INFO", "a long first entry that makes the file big") + "\n")
        path = db_path.parent.parent / "logs" / "index.log"
        calls = []

        def stop():
            calls.append(1)
            if len(calls) == 1:  # a daily rollover: a fresh, shorter file
                path.write_text(_line("INFO", "x") + "\n", encoding="utf-8")
            return len(calls) > 2

        assert [e.message for e in _IndexLog.follow(db_path, stop=stop)] == ["x"]

    def test_a_bad_level_is_rejected_up_front(self, db_path):
        with pytest.raises(errors.InvalidLogRequestError):
            next(_IndexLog.follow(db_path, level="loud"))


class TestExport:
    @pytest.fixture
    def entries(self, db_path):
        _write(
            db_path,
            "\n".join(
                [_line("INFO", "a", 0), _line("ERROR", "b", 1), "Traceback", _line("INFO", "c", 2)]
            )
            + "\n",
        )
        return db_path

    def test_writes_every_entry_as_plain_text(self, entries, tmp_path):
        out = tmp_path / "out.txt"

        assert _IndexLog.export(entries, out) == 3
        assert out.read_text(encoding="utf-8").splitlines()[1:3] == [
            _line("ERROR", "b", 1),
            "Traceback",
        ]

    def test_uses_the_same_selection_as_reading(self, entries, tmp_path):
        out = tmp_path / "out.txt"

        assert _IndexLog.export(entries, out, level="error") == 1
        assert out.read_text(encoding="utf-8") == _line("ERROR", "b", 1) + "\nTraceback\n"

    def test_lines_keeps_only_the_most_recent(self, entries, tmp_path):
        out = tmp_path / "out.txt"

        assert _IndexLog.export(entries, out, lines=1) == 1
        assert out.read_text(encoding="utf-8") == _line("INFO", "c", 2) + "\n"

    def test_order(self, entries, tmp_path):
        out = tmp_path / "out.txt"

        _IndexLog.export(entries, out, order="desc")

        assert out.read_text(encoding="utf-8").startswith(_line("INFO", "c", 2))

    def test_nothing_selected_writes_an_empty_file(self, entries, tmp_path):
        out = tmp_path / "out.txt"
        out.write_text("old")

        assert _IndexLog.export(entries, out, contains="zzz") == 0
        assert out.read_text() == ""

    def test_an_existing_file_is_overwritten(self, entries, tmp_path):
        out = tmp_path / "out.txt"
        out.write_text("old")

        _IndexLog.export(entries, out)

        assert "old" not in out.read_text()

    def test_a_missing_log_is_reported(self, db_path, tmp_path):
        with pytest.raises(errors.LogNotFoundError):
            _IndexLog.export(db_path, tmp_path / "out.txt")
