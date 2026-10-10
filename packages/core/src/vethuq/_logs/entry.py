"""One log entry: a log line plus any traceback lines that follow it."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

from vethuq.enums import LogLevel

# Every record starts with `YYYY-MM-DD HH:MM:SS,mmm LEVEL`; lines without it (a traceback)
# belong to the record above.
_START = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (\w+) ")
_PARSE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (\w+) \[(.*?)\] ([^\s:]+): (.*)$", re.DOTALL
)
_LEVELS = [level.value for level in LogLevel]


@dataclass(frozen=True)
class _Entry:
    raw: str
    timestamp: datetime | None  # local time, as logged
    level: LogLevel | None  # None if the entry isn't in the usual format
    thread: str | None
    logger: str | None
    message: str

    @staticmethod
    def parse(raw: str) -> _Entry:
        match = _PARSE.match(raw)
        if match is None:
            return _Entry(
                raw=raw, timestamp=None, level=None, thread=None, logger=None, message=raw
            )
        stamp, name, thread, logger, message = match.groups()
        name = name.lower()
        if name == "critical":
            name = LogLevel.ERROR.value
        return _Entry(
            raw=raw,
            timestamp=datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S,%f"),
            level=LogLevel(name) if name in _LEVELS else None,
            thread=thread,
            logger=logger,
            message=message,
        )

    @staticmethod
    def starts_record(line: str) -> bool:
        return _START.match(line) is not None

    @staticmethod
    def group(lines: Iterable[str]) -> Iterator[str]:
        """Group raw lines into records, so a traceback stays with the line that raised it."""
        current: list[str] = []
        for line in lines:
            if _START.match(line) and current:
                yield "\n".join(current)
                current = []
            current.append(line)
        if current:
            yield "\n".join(current)

    def passes(self, minimum: LogLevel | None, contains: str | None) -> bool:
        """Whether the entry is at or above `minimum` (entries of unknown format always pass
        the level) and its message, traceback included, contains `contains` (ignoring case)."""
        if minimum is not None and self.level is not None:
            if _LEVELS.index(self.level.value) < _LEVELS.index(minimum.value):
                return False
        return contains is None or contains.casefold() in self.message.casefold()
