"""VethuQ's logs: `VethuQ().logs`.

client.logs.cli.tail(lines=20)
client.logs.database.read(day="2026-10-09", level="warning")
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import ClassVar

from vethuq._db import _Database
from vethuq._logs import (
    _CliLog,
    _DatabaseLog,
    _Entry,
    _IndexLog,
    _Log,
    _Logs,
    _PolicyLog,
    _UiLog,
)
from vethuq.enums import LogComponent, LogLevel, SortOrder

__all__ = [
    "CliLog",
    "DatabaseLog",
    "IndexLog",
    "Log",
    "LogComponent",
    "LogEntry",
    "LogFile",
    "LogLevel",
    "Logs",
    "PolicyLog",
    "SortOrder",
    "UiLog",
]


@dataclass(frozen=True)
class LogEntry:
    """One entry of a log: a log line plus any traceback under it."""

    timestamp: datetime | None  # local time, as logged; None if the entry isn't in the usual format
    level: LogLevel | None
    thread: str | None
    logger: str | None
    message: str  # includes a traceback, if there is one
    raw: str  # the entry exactly as written to the file

    @classmethod
    def _from_entry(cls, entry: _Entry) -> LogEntry:
        return cls(
            timestamp=entry.timestamp,
            level=entry.level,
            thread=entry.thread,
            logger=entry.logger,
            message=entry.message,
            raw=entry.raw,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "level": self.level.value if self.level else None,
            "thread": self.thread,
            "logger": self.logger,
            "message": self.message,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class LogFile:
    """A component's log file for one day."""

    component: LogComponent
    path: str
    exists: bool
    size_bytes: int | None  # None if the file doesn't exist
    modified_at: str | None  # UTC, ISO 8601; None if the file doesn't exist
    days: tuple[date, ...]  # every day that has a log for the component, oldest first

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component.value,
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "days": [day.isoformat() for day in self.days],
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Log:
    """One component's log. The classes below say which; use them through `VethuQ().logs`.

    Not created directly.
    """

    _log: ClassVar[type[_Log]]

    def __init__(self, database: _Database) -> None:
        self._database = database

    @property
    def component(self) -> LogComponent:
        """Which component this log belongs to."""
        return self._log.COMPONENT

    @property
    def description(self) -> str:
        """What the component logs."""
        return self._log.DESCRIPTION

    @property
    def _db_path(self) -> Path:
        return self._database.db_path

    def file(self, day: date | str | None = None) -> LogFile:
        """The log file for `day` (`datetime.date` or `"YYYY-MM-DD"`); today's by default.

        Nothing is created: `exists` says whether the file is there.
        """
        from datetime import UTC

        path = self._log.file_path(self._db_path, self._log.parse_day(day))
        stat = path.stat() if path.is_file() else None
        return LogFile(
            component=self.component,
            path=str(path),
            exists=stat is not None,
            size_bytes=stat.st_size if stat else None,
            modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat() if stat else None,
            days=tuple(self._log.days(self._db_path)),
        )

    def tail(
        self,
        lines: int = 40,
        *,
        day: date | str | None = None,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        order: SortOrder | str = SortOrder.ASC,
    ) -> list[LogEntry]:
        """The most recent `lines` entries of a day's log.

        `level` keeps entries at or above it, `contains` entries whose message contains that text
        (ignoring case; the logger, thread and level are not searched), and `order` sorts by
        time (`ASC`: oldest first, the default). Raises `LogNotFoundError` if there is no log
        for the day and `InvalidLogRequestError` for a `lines`, `day`, `level` or `order` that
        can't be used.
        """
        entries = self._log.tail(
            self._db_path, lines=lines, day=day, level=level, contains=contains, order=order
        )
        return [LogEntry._from_entry(e) for e in entries]

    def read(
        self,
        *,
        day: date | str | None = None,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        order: SortOrder | str = SortOrder.ASC,
    ) -> list[LogEntry]:
        """Every entry of a day's log, filtered and sorted like `tail`."""
        entries = self._log.read(
            self._db_path, day=day, level=level, contains=contains, order=order
        )
        return [LogEntry._from_entry(e) for e in entries]

    def follow(
        self,
        *,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Iterator[LogEntry]:
        """Yield entries as they are written to today's log, like `tail -f`.

        It starts from the current end of the file and runs until `stop()` returns True (never,
        when `stop` is left out), so end it with `break` or Ctrl+C.
        """
        for entry in self._log.follow(self._db_path, level=level, contains=contains, stop=stop):
            yield LogEntry._from_entry(entry)

    def export(
        self,
        path: str | Path,
        *,
        lines: int | None = None,
        day: date | str | None = None,
        level: LogLevel | str | None = None,
        contains: str | None = None,
        order: SortOrder | str = SortOrder.ASC,
    ) -> int:
        """Write the selected entries to `path` as plain text, one entry per line, and return
        how many were written. With `lines`, only the most recent that many; otherwise all."""
        return self._log.export(
            self._db_path, path, lines=lines, day=day, level=level, contains=contains, order=order
        )

    def logger(self) -> logging.Logger:
        """The standard `logging.Logger` for this component, set up to write to its log file.

        This is how the command line, the desktop app and the indexer write their logs. The
        level and the days kept come from the log settings.
        """
        return self._log.setup(self._db_path)


class DatabaseLog(Log):
    """The database log: opening it, schema upgrades, sources and settings changes."""

    _log = _DatabaseLog


class IndexLog(Log):
    """The index log: the background index runs and every OCR worker thread."""

    _log = _IndexLog


class UiLog(Log):
    """The desktop app's log."""

    _log = _UiLog


class CliLog(Log):
    """The command line's log: each command that ran and how it finished."""

    _log = _CliLog


class PolicyLog(Log):
    """The policy log: fetching, verifying and applying the signed policy, and the update check."""

    _log = _PolicyLog


class Logs:
    """VethuQ's logs, one attribute per component.

    Not created directly: use `VethuQ().logs`.
    """

    def __init__(self, database: _Database) -> None:
        self.database = DatabaseLog(database)
        self.index = IndexLog(database)
        self.ui = UiLog(database)
        self.cli = CliLog(database)
        self.policy = PolicyLog(database)

    def list(self) -> list[LogFile]:
        """Today's log file of every component: database, index, ui, cli and policy."""
        return [log.file() for log in (self.database, self.index, self.ui, self.cli, self.policy)]

    def get(self, component: LogComponent | str) -> Log:
        """The log of a component given as a `LogComponent` or its name (`"cli"`).

        Raises `InvalidLogRequestError` for a name that isn't a component.
        """
        return getattr(self, _Logs.get(component).COMPONENT.value)
