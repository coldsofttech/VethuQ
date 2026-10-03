"""Per-component log files in the data directory's `logs/` folder.

| Component | File | Logger | Covers |
| --- | --- | --- | --- |
| `database` | `database.log` | `vethuq.database` | schema, migrations, purges, integrity |
| `index` | `index.log` | `vethuq.index` | background index runs and every OCR worker thread |
| `ui` | `ui.log` | `vethuq.ui` | the desktop app |
| `cli` | `cli.log` | `vethuq.cli` | `vethuq` commands run from a terminal |

One file per day, kept for `log_retention_days` days (`vethuq settings logs
retention`). Verbosity follows the `log_level` setting (`vethuq settings logs
level`). Both are read when a component's logging is first set up in a process.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from vethuq_core.paths import Paths


class LogNotFoundError(FileNotFoundError):
    """The requested component has no log file for that day."""


class Logs:
    COMPONENTS = {
        "database": "database.log",
        "index": "index.log",
        "ui": "ui.log",
        "cli": "cli.log",
    }

    DEFAULT_RETENTION_DAYS = 15
    DEFAULT_LEVEL = "info"
    _FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    LEVELS = ("debug", "info", "warning", "error")
    # A record starts with `YYYY-MM-DD HH:MM:SS,mmm LEVEL`; lines without it (a
    # traceback) belong to the record above.
    _RECORD_START = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (\w+) ")
    _FOLLOW_POLL_SECONDS = 0.5

    class _SafeRotatingFileHandler(TimedRotatingFileHandler):
        """Starts a new file each day (old ones become `<name>.log.YYYY-MM-DD`) and keeps
        only the most recent `backupCount` days, but keeps logging if rotation fails.

        Several processes (the CLI, the desktop app, an index worker) can append to
        the same file; on Windows a rotation attempted while another process holds
        the file open raises `PermissionError`. Skipping it just retries on a later
        record instead of losing the log line.
        """

        def doRollover(self) -> None:  # noqa: N802 - stdlib override
            try:
                super().doRollover()
            except OSError:
                if self.stream is None:
                    self.stream = self._open()

    @staticmethod
    def get_logger(component: str) -> logging.Logger:
        """The logger for a component (`database`, `index`, `ui` or `cli`)."""
        if component not in Logs.COMPONENTS:
            raise ValueError(f"unknown log component: {component!r}")
        return logging.getLogger(f"vethuq.{component}")

    @staticmethod
    def _read_setting(db_path: Path, key: str) -> str | None:
        """A raw settings-table value, without going through `Db.connect()` (which itself
        logs) - None if the database or setting doesn't exist yet."""
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return row[0] if row is not None else None

    @staticmethod
    def read_level(db_path: Path) -> int:
        """The `log_level` setting as a `logging` level - INFO if unset."""
        name = Logs._read_setting(db_path, "log_level") or Logs.DEFAULT_LEVEL
        return getattr(logging, str(name).upper(), logging.INFO)

    @staticmethod
    def read_retention_days(db_path: Path) -> int:
        """The `log_retention_days` setting - 15 if unset or invalid."""
        try:
            days = int(
                Logs._read_setting(db_path, "log_retention_days") or Logs.DEFAULT_RETENTION_DAYS
            )
        except ValueError:
            return Logs.DEFAULT_RETENTION_DAYS
        return days if days >= 1 else Logs.DEFAULT_RETENTION_DAYS

    @staticmethod
    def prune_old(log_file: Path, retention_days: int) -> None:
        """Delete `<log_file>.YYYY-MM-DD` files dated more than `retention_days` days ago.

        The handler only prunes when it rolls over, so this makes a shortened
        retention take effect as soon as a process starts logging.
        """
        cutoff = (datetime.now() - timedelta(days=retention_days)).date()
        for path in log_file.parent.glob(log_file.name + ".*"):
            try:
                day = datetime.strptime(path.name[len(log_file.name) + 1 :], "%Y-%m-%d").date()
                if day < cutoff:
                    path.unlink()
            except (ValueError, OSError):
                continue

    @staticmethod
    def setup(component: str, db_path: Path) -> logging.Logger:
        """Attach the component's rotating log file to its logger (once per log file).

        Never raises: if the log file can't be opened, logging is simply skipped
        rather than breaking the command or app.
        """
        logger = Logs.get_logger(component)
        log_file = Paths.logs_dir(db_path) / Logs.COMPONENTS[component]
        current = [h for h in logger.handlers if isinstance(h, Logs._SafeRotatingFileHandler)]
        if current and Path(current[0].baseFilename) == log_file.resolve():
            return logger
        retention_days = Logs.read_retention_days(db_path)
        Logs.prune_old(log_file, retention_days)
        for old in list(logger.handlers):  # pointed at another data dir (e.g. a different db_path)
            logger.removeHandler(old)
            old.close()
        try:
            handler = Logs._SafeRotatingFileHandler(
                log_file,
                when="midnight",
                backupCount=retention_days,
                encoding="utf-8",
            )
        except OSError:
            logger.addHandler(logging.NullHandler())
            return logger
        handler.setFormatter(logging.Formatter(Logs._FORMAT))
        logger.addHandler(handler)
        logger.setLevel(Logs.read_level(db_path))
        logger.propagate = False
        return logger

    @staticmethod
    def log_file(component: str, db_path: Path, day: date | None = None) -> Path:
        """Path of a component's log file: today's, or the rotated file for `day`."""
        Logs.get_logger(component)  # validates the component name
        path = Paths.logs_dir(db_path) / Logs.COMPONENTS[component]
        if day is None or day == date.today():
            return path
        return path.with_name(f"{path.name}.{day.isoformat()}")

    @staticmethod
    def level_of(record: str) -> str:
        """The lowercase level of a record (`"error"`, ...), or `""` if its format is unknown."""
        match = Logs._RECORD_START.match(record)
        return match.group(1).lower() if match else ""

    @staticmethod
    def validate_request(
        component: str,
        *,
        level: str | None = None,
        lines: int = 40,
        day: str | None = None,
        follow: bool = False,
        export: str | None = None,
    ) -> date | None:
        """Check a log-reading request and return the parsed `day` (None for today).

        Raises `ValueError` with a user-ready message for an unknown component or
        level, `lines` below 1, a `day` that isn't `YYYY-MM-DD`, or `follow`
        combined with `day` or `export`.
        """
        if component not in Logs.COMPONENTS:
            raise ValueError(
                f"unknown component {component!r}; choose one of: {', '.join(Logs.COMPONENTS)}"
            )
        if level is not None and level not in Logs.LEVELS:
            raise ValueError(f"level must be one of: {', '.join(Logs.LEVELS)}")
        if lines < 1:
            raise ValueError("--tail must be at least 1")
        selected_day: date | None = None
        if day is not None:
            try:
                selected_day = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("--date must be in YYYY-MM-DD format") from None
        if follow and (selected_day is not None or export is not None):
            raise ValueError("--follow can't be combined with --date or --export")
        return selected_day

    @staticmethod
    def export(records: list[str], path: str | Path) -> int:
        """Write `records` to `path`, one per line, and return how many were written."""
        Path(path).write_text("\n".join(records) + ("\n" if records else ""), encoding="utf-8")
        return len(records)

    @staticmethod
    def _validate_level(level: str | None) -> None:
        if level is not None and level not in Logs.LEVELS:
            raise ValueError(f"level must be one of {Logs.LEVELS}")

    @staticmethod
    def _records(lines: Iterator[str]) -> Iterator[str]:
        """Group raw lines into records, so a traceback stays with the line that raised it."""
        current: list[str] = []
        for line in lines:
            if Logs._RECORD_START.match(line) and current:
                yield "\n".join(current)
                current = []
            current.append(line)
        if current:
            yield "\n".join(current)

    @staticmethod
    def _passes(record: str, level: str | None) -> bool:
        """Whether a record is at or above `level` (records of unknown format always pass)."""
        if level is None:
            return True
        match = Logs._RECORD_START.match(record)
        if match is None or match.group(1).lower() not in Logs.LEVELS:
            return True
        return Logs.LEVELS.index(match.group(1).lower()) >= Logs.LEVELS.index(level)

    @staticmethod
    def tail(
        component: str,
        db_path: Path,
        *,
        lines: int = 40,
        level: str | None = None,
        day: date | None = None,
    ) -> list[str]:
        """The last `lines` records of a component's log, optionally only at or above `level`.

        A record is one log line plus any traceback lines that follow it.
        Raises `LogNotFoundError` if there is no log file for that day and
        `ValueError` for an unknown component, level or a `lines` below 1.
        """
        Logs._validate_level(level)
        if lines < 1:
            raise ValueError("lines must be at least 1")
        path = Logs.log_file(component, db_path, day)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                raw = (line.rstrip("\r\n") for line in handle)
                records = [r for r in Logs._records(raw) if Logs._passes(r, level)]
        except FileNotFoundError:
            raise LogNotFoundError(f"No {component} log for {day or 'today'} at {path}") from None
        return records[-lines:]

    @staticmethod
    def follow(
        component: str,
        db_path: Path,
        *,
        level: str | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        """Yield records as they're appended to today's log, starting from its current end.

        Runs until `stop()` returns True (never, when `stop` is None), so callers
        normally end it with Ctrl+C. Survives the daily rollover by reopening
        the file when it shrinks or is replaced.
        """
        Logs._validate_level(level)
        path = Logs.log_file(component, db_path)
        position = path.stat().st_size if path.exists() else 0
        pending: list[str] = []
        while not (stop is not None and stop()):
            size = path.stat().st_size if path.exists() else 0
            if size < position:  # rolled over to a fresh file
                position = 0
            if size > position:
                with open(path, "rb") as handle:
                    handle.seek(position)
                    chunk = handle.read()
                    position = handle.tell()
                text = chunk.decode("utf-8", errors="replace")
                for line in text.splitlines():
                    if Logs._RECORD_START.match(line) and pending:
                        record = "\n".join(pending)
                        pending = []
                        if Logs._passes(record, level):
                            yield record
                    pending.append(line)
            elif pending:
                # Idle: whatever is buffered is a complete record.
                record = "\n".join(pending)
                pending = []
                if Logs._passes(record, level):
                    yield record
            else:
                time.sleep(Logs._FOLLOW_POLL_SECONDS)
