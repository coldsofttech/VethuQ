"""VethuQ's log files: writing them, and reading them back.

One class per component (`_DatabaseLog`, `_IndexLog`, `_UiLog`, `_CliLog`), each with its own
file in the data folder's `logs/` directory and its own logger (`vethuq.<component>`). One file
per day, kept for `log_retention_days` days; verbosity follows the `log_level` setting. Both are
read when a component's logging is first set up in a process.

Loggers are process-wide: two clients on different databases in one process share them, and the
most recently set up one decides where each component writes.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import ClassVar

from vethuq._errors import _InvalidLogRequestError, _LogNotFoundError
from vethuq._logs.entry import _Entry
from vethuq._paths import _Paths
from vethuq.enums import LogComponent, LogLevel, SortOrder


class _SafeRotatingFileHandler(TimedRotatingFileHandler):
    """Starts a new file each day (old ones become `<name>.log.YYYY-MM-DD`) and keeps only the
    most recent `backupCount` days, but keeps logging if rotation fails.

    Several processes (the CLI, the desktop app, an index worker) can append to the same file;
    on Windows a rotation attempted while another process holds the file open raises
    `PermissionError`. Skipping it just retries on a later record instead of losing the line.
    """

    def doRollover(self) -> None:  # noqa: N802 - stdlib override
        try:
            super().doRollover()
        except OSError:
            if self.stream is None:
                self.stream = self._open()


class _Log:
    """A component's log. Subclasses name the component and its file."""

    COMPONENT: ClassVar[LogComponent]
    FILENAME: ClassVar[str]
    DESCRIPTION: ClassVar[str]

    LEVEL_KEY = "log_level"
    RETENTION_DAYS_KEY = "log_retention_days"
    DEFAULT_LEVEL = LogLevel.INFO
    DEFAULT_RETENTION_DAYS = 15
    DEFAULT_TAIL = 40
    FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    FOLLOW_POLL_SECONDS = 0.5

    # ----- the logger -----------------------------------------------------------------------

    @classmethod
    def logger(cls) -> logging.Logger:
        return logging.getLogger(f"vethuq.{cls.COMPONENT.value}")

    @classmethod
    def file_path(cls, db_path: Path, day: date | None = None) -> Path:
        """The component's log file: today's, or the rotated file for `day`. Creates nothing."""
        path = _Paths.logs_dir(db_path, create=False) / cls.FILENAME
        if day is None or day == date.today():
            return path
        return path.with_name(f"{path.name}.{day.isoformat()}")

    @classmethod
    def days(cls, db_path: Path) -> list[date]:
        """The days that have a log, oldest first (today included once it has one)."""
        path = cls.file_path(db_path)
        found: list[date] = []
        for rotated in path.parent.glob(path.name + ".*"):
            try:
                stamp = rotated.name[len(path.name) + 1 :]
                found.append(datetime.strptime(stamp, "%Y-%m-%d").date())
            except ValueError:
                continue
        if path.exists():
            found.append(date.today())
        return sorted(set(found))

    # ----- settings ------------------------------------------------------------------------

    @staticmethod
    def _read_setting(db_path: Path, key: str) -> str | None:
        """A raw settings-table value, read without opening the database through SQLAlchemy
        (which itself logs). None if the database or the setting doesn't exist yet."""
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return row[0] if row is not None else None

    @classmethod
    def read_level(cls, db_path: Path) -> LogLevel:
        value = cls._read_setting(db_path, cls.LEVEL_KEY)
        try:
            return LogLevel(value) if value is not None else cls.DEFAULT_LEVEL
        except ValueError:
            return cls.DEFAULT_LEVEL

    @classmethod
    def read_retention_days(cls, db_path: Path) -> int:
        try:
            days = int(
                cls._read_setting(db_path, cls.RETENTION_DAYS_KEY) or cls.DEFAULT_RETENTION_DAYS
            )
        except ValueError:
            return cls.DEFAULT_RETENTION_DAYS
        return days if days >= 1 else cls.DEFAULT_RETENTION_DAYS

    # ----- writing -------------------------------------------------------------------------

    @staticmethod
    def prune_old(log_file: Path, retention_days: int) -> None:
        """Delete `<log_file>.YYYY-MM-DD` files dated more than `retention_days` days ago.

        The handler only prunes when it rolls over, so this makes a shortened retention take
        effect as soon as a process starts logging.
        """
        cutoff = (datetime.now() - timedelta(days=retention_days)).date()
        for path in log_file.parent.glob(log_file.name + ".*"):
            try:
                day = datetime.strptime(path.name[len(log_file.name) + 1 :], "%Y-%m-%d").date()
                if day < cutoff:
                    path.unlink()
            except (ValueError, OSError):
                continue

    @classmethod
    def _handlers(cls) -> list[_SafeRotatingFileHandler]:
        return [h for h in cls.logger().handlers if isinstance(h, _SafeRotatingFileHandler)]

    @classmethod
    def setup(cls, db_path: Path) -> logging.Logger:
        """Attach the component's rotating log file to its logger (once per log file).

        Never raises: if the log file can't be opened, logging is simply skipped rather than
        breaking the caller.
        """
        logger = cls.logger()
        try:
            log_file = _Paths.logs_dir(db_path) / cls.FILENAME
        except OSError:
            return logger
        current = cls._handlers()
        if current and Path(current[0].baseFilename).resolve() == log_file.resolve():
            return logger
        retention_days = cls.read_retention_days(db_path)
        cls.prune_old(log_file, retention_days)
        cls.detach()  # pointed at another data folder (a different database)
        try:
            handler = _SafeRotatingFileHandler(
                log_file, when="midnight", backupCount=retention_days, encoding="utf-8"
            )
        except OSError:
            logger.addHandler(logging.NullHandler())
            return logger
        handler.setFormatter(logging.Formatter(cls.FORMAT))
        logger.addHandler(handler)
        logger.setLevel(cls.read_level(db_path).value.upper())
        logger.propagate = False
        return logger

    @classmethod
    def reconfigure(cls, db_path: Path) -> None:
        """Apply the level and retention settings now to a component already logging to this
        database's file."""
        log_file = (_Paths.logs_dir(db_path, create=False) / cls.FILENAME).resolve()
        for handler in cls._handlers():
            if Path(handler.baseFilename).resolve() == log_file:
                handler.backupCount = cls.read_retention_days(db_path)
                cls.prune_old(log_file, handler.backupCount)
                cls.logger().setLevel(cls.read_level(db_path).value.upper())

    @classmethod
    def detach(cls) -> None:
        """Stop writing the component's log file and release it."""
        logger = cls.logger()
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    # ----- reading -------------------------------------------------------------------------

    @staticmethod
    def parse_day(day: date | str | None) -> date | None:
        if day is None or isinstance(day, date):
            return day.date() if isinstance(day, datetime) else day
        try:
            return datetime.strptime(day, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            raise _InvalidLogRequestError(
                f"The day {day!r} isn't a date.", "Use YYYY-MM-DD, or a datetime.date."
            ) from None

    @staticmethod
    def parse_level(level: LogLevel | str | None) -> LogLevel | None:
        if level is None:
            return None
        try:
            return LogLevel(level)
        except ValueError:
            options = ", ".join(member.value for member in LogLevel)
            raise _InvalidLogRequestError(
                f"The level {level!r} isn't a log level.", f"Use one of: {options}."
            ) from None

    @staticmethod
    def parse_order(order: SortOrder | str) -> SortOrder:
        try:
            return SortOrder(order)
        except ValueError:
            options = ", ".join(member.value for member in SortOrder)
            raise _InvalidLogRequestError(
                f"The order {order!r} isn't a sort order.", f"Use one of: {options}."
            ) from None

    @staticmethod
    def check_lines(lines: int) -> None:
        if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
            raise _InvalidLogRequestError(
                f"lines must be a whole number of at least 1, not {lines!r}.",
                "Use read() to get every entry of a day.",
            )

    @classmethod
    def _load(cls, db_path: Path, day: date | None) -> list[_Entry]:
        path = cls.file_path(db_path, day)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = [line.rstrip("\r\n") for line in handle]
        except FileNotFoundError:
            raise _LogNotFoundError(
                f"No {cls.COMPONENT.value} log for {day or 'today'} at {path}",
                "Use list() to see which days have a log.",
            ) from None
        return [_Entry.parse(record) for record in _Entry.group(lines)]

    @classmethod
    def read(
        cls,
        db_path: Path,
        *,
        day: date | str | None = None,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        order: SortOrder | str = SortOrder.ASC,
    ) -> list[_Entry]:
        """Every entry of a day, filtered and sorted by time (oldest first by default)."""
        minimum, sort = cls.parse_level(level), cls.parse_order(order)
        entries = [e for e in cls._load(db_path, cls.parse_day(day)) if e.passes(minimum, contains)]
        return entries[::-1] if sort is SortOrder.DESC else entries

    @classmethod
    def tail(
        cls,
        db_path: Path,
        *,
        lines: int = DEFAULT_TAIL,
        day: date | str | None = None,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        order: SortOrder | str = SortOrder.ASC,
    ) -> list[_Entry]:
        """The most recent `lines` entries of a day, filtered, in the order asked for."""
        cls.check_lines(lines)
        sort = cls.parse_order(order)
        entries = cls.read(db_path, day=day, level=level, contains=contains)[-lines:]
        return entries[::-1] if sort is SortOrder.DESC else entries

    @classmethod
    def follow(
        cls,
        db_path: Path,
        *,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Iterator[_Entry]:
        """Yield entries as they're appended to today's log, starting from its current end.

        Runs until `stop()` returns True (never, when `stop` is None). Survives the daily
        rollover by reopening the file when it shrinks or is replaced.
        """
        minimum = cls.parse_level(level)
        path = cls.file_path(db_path)
        position = path.stat().st_size if path.exists() else 0
        pending: list[str] = []

        def emit() -> Iterator[_Entry]:
            record = "\n".join(pending)
            pending.clear()
            entry = _Entry.parse(record)
            if entry.passes(minimum, contains):
                yield entry

        while not (stop is not None and stop()):
            size = path.stat().st_size if path.exists() else 0
            if size < position:  # rolled over to a fresh file
                position = 0
            if size > position:
                with open(path, "rb") as handle:
                    handle.seek(position)
                    chunk = handle.read()
                    position = handle.tell()
                for line in chunk.decode("utf-8", errors="replace").splitlines():
                    if _Entry.starts_record(line) and pending:
                        yield from emit()
                    pending.append(line)
            elif pending:
                # Idle: whatever is buffered is a complete record.
                yield from emit()
            else:
                time.sleep(cls.FOLLOW_POLL_SECONDS)

    @classmethod
    def export(
        cls,
        db_path: Path,
        path: str | Path,
        *,
        lines: int | None = None,
        day: date | str | None = None,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        order: SortOrder | str = SortOrder.ASC,
    ) -> int:
        """Write the selected entries to `path` as plain text, one entry per line (a traceback
        stays with its entry), and return how many were written."""
        if lines is None:
            entries = cls.read(db_path, day=day, level=level, contains=contains, order=order)
        else:
            entries = cls.tail(
                db_path, lines=lines, day=day, level=level, contains=contains, order=order
            )
        text = "\n".join(entry.raw for entry in entries)
        Path(path).write_text(text + "\n" if entries else "", encoding="utf-8")
        return len(entries)


class _DatabaseLog(_Log):
    COMPONENT = LogComponent.DATABASE
    FILENAME = "database.log"
    DESCRIPTION = "The database: opening it, schema upgrades, sources and settings changes."


class _IndexLog(_Log):
    COMPONENT = LogComponent.INDEX
    FILENAME = "index.log"
    DESCRIPTION = "Indexing: the background index runs and every OCR worker thread."


class _UiLog(_Log):
    COMPONENT = LogComponent.UI
    FILENAME = "ui.log"
    DESCRIPTION = "The VethuQ desktop app."


class _CliLog(_Log):
    COMPONENT = LogComponent.CLI
    FILENAME = "cli.log"
    DESCRIPTION = "The `vethuq` command line: each command that ran and how it finished."


class _Logs:
    ALL: dict[LogComponent, type[_Log]] = {
        LogComponent.DATABASE: _DatabaseLog,
        LogComponent.INDEX: _IndexLog,
        LogComponent.UI: _UiLog,
        LogComponent.CLI: _CliLog,
    }

    @staticmethod
    def get(component: LogComponent | str) -> type[_Log]:
        try:
            return _Logs.ALL[LogComponent(component)]
        except ValueError:
            options = ", ".join(member.value for member in LogComponent)
            raise _InvalidLogRequestError(
                f"Unknown log component {component!r}.", f"Use one of: {options}."
            ) from None

    @staticmethod
    def reconfigure(db_path: Path) -> None:
        for log in _Logs.ALL.values():
            log.reconfigure(db_path)

    @staticmethod
    def detach_all() -> None:
        for log in _Logs.ALL.values():
            log.detach()
