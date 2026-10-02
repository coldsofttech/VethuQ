import logging
from datetime import date, datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

import pytest
from vethuq_core.db import Db
from vethuq_core.logs import LogNotFoundError, Logs
from vethuq_core.settings import LogSettings


def _reset(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


@pytest.fixture
def cli_logger():
    logger = Logs.get_logger("cli")
    _reset(logger)
    yield logger
    _reset(logger)


class TestLogs:
    def test_get_logger_rejects_unknown_component(self):
        with pytest.raises(ValueError):
            Logs.get_logger("nope")

    def test_setup_writes_to_component_file(self, tmp_path, cli_logger):
        db_path = tmp_path / "db" / "vethuq.db"

        Logs.setup("cli", db_path)
        cli_logger.info("hello from cli")
        for handler in cli_logger.handlers:
            handler.flush()

        assert "hello from cli" in (tmp_path / "logs" / "cli.log").read_text(encoding="utf-8")
        assert cli_logger.level == logging.INFO

    def test_level_setting_controls_logger_level(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        db_path.parent.mkdir()
        conn = Db.connect(db_path)
        LogSettings.set_level(conn, "debug")
        conn.close()

        assert Logs.read_level(db_path) == logging.DEBUG
        assert Logs.read_level(tmp_path / "missing.db") == logging.INFO

    def test_connect_logs_schema_creation_to_database_log(self, tmp_path):
        logger = Logs.get_logger("database")
        _reset(logger)
        db_path = tmp_path / "db" / "vethuq.db"
        db_path.parent.mkdir()
        try:
            Db.connect(db_path).close()
            for handler in logger.handlers:
                handler.flush()
            text = (tmp_path / "logs" / "database.log").read_text(encoding="utf-8")
        finally:
            _reset(logger)

        assert "Created database schema" in text

    def test_read_retention_days_reads_setting_and_defaults(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        assert Logs.read_retention_days(db_path) == 15

        conn = Db.connect(db_path)
        LogSettings.set_retention_days(conn, 4)
        conn.close()

        assert Logs.read_retention_days(db_path) == 4

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

        Logs.prune_old(log_file, 5)

        assert log_file.exists()
        assert recent.exists()
        assert boundary.exists()
        assert not old.exists()
        assert unrelated.exists()

    def test_handler_rotates_daily_and_keeps_retention_days(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"
        db_path.parent.mkdir()
        conn = Db.connect(db_path)
        LogSettings.set_retention_days(conn, 9)
        conn.close()
        logger = Logs.get_logger("ui")
        _reset(logger)
        try:
            Logs.setup("ui", db_path)
            handler = logger.handlers[0]
            assert isinstance(handler, TimedRotatingFileHandler)
            assert handler.when == "MIDNIGHT"
            assert handler.backupCount == 9
        finally:
            _reset(logger)


def _entry(level: str, message: str, second: int = 0) -> str:
    return f"2026-10-01 10:00:{second:02d},000 {level} [MainThread] vethuq.index: {message}"


def _write_log(tmp_path, text: str, suffix: str = ""):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / f"index.log{suffix}").write_text(text, encoding="utf-8")
    return tmp_path / "db" / "vethuq.db"


class TestLogReading:
    def test_tail_returns_the_last_entries_oldest_first(self, tmp_path):
        lines = [_entry("INFO", f"m{i}", i) for i in range(5)]
        db_path = _write_log(tmp_path, "\n".join(lines) + "\n")

        assert Logs.tail("index", db_path, lines=2) == lines[-2:]

    def test_tail_keeps_a_traceback_with_its_entry(self, tmp_path):
        crash = (
            _entry("ERROR", "crashed", 1) + "\nTraceback (most recent call last):\nValueError: x"
        )
        text = _entry("INFO", "start") + "\n" + crash + "\n" + _entry("INFO", "end", 2) + "\n"
        db_path = _write_log(tmp_path, text)

        assert Logs.tail("index", db_path, lines=2) == [crash, _entry("INFO", "end", 2)]

    def test_tail_filters_by_minimum_level(self, tmp_path):
        text = "\n".join([_entry("INFO", "a"), _entry("WARNING", "b", 1), _entry("ERROR", "c", 2)])
        db_path = _write_log(tmp_path, text + "\n")

        result = Logs.tail("index", db_path, level="warning")

        assert [r.split(": ")[1] for r in result] == ["b", "c"]

    def test_tail_reads_a_rotated_day(self, tmp_path):
        db_path = _write_log(tmp_path, _entry("INFO", "old day") + "\n", suffix=".2026-09-28")

        result = Logs.tail("index", db_path, day=date(2026, 9, 28))

        assert result == [_entry("INFO", "old day")]

    def test_tail_raises_when_there_is_no_log(self, tmp_path):
        with pytest.raises(LogNotFoundError):
            Logs.tail("index", tmp_path / "db" / "vethuq.db")

    def test_tail_rejects_bad_arguments(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"

        with pytest.raises(ValueError):
            Logs.tail("nope", db_path)
        with pytest.raises(ValueError):
            Logs.tail("index", db_path, level="loud")
        with pytest.raises(ValueError):
            Logs.tail("index", db_path, lines=0)

    def test_follow_yields_entries_appended_after_it_starts(self, tmp_path, monkeypatch):
        db_path = _write_log(tmp_path, _entry("INFO", "before") + "\n")
        log_file = tmp_path / "logs" / "index.log"
        monkeypatch.setattr(Logs, "_FOLLOW_POLL_SECONDS", 0)
        ticks = {"n": 0}

        def stop() -> bool:
            ticks["n"] += 1
            if ticks["n"] == 2:
                with open(log_file, "a", encoding="utf-8") as handle:
                    handle.write(_entry("INFO", "after", 1) + "\n")
            return ticks["n"] > 6

        assert list(Logs.follow("index", db_path, stop=stop)) == [_entry("INFO", "after", 1)]
