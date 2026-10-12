"""Logs for the interface: the files, a day's entries, following, and export."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

LEVELS = ("debug", "info", "warning", "error")
MAX_ENTRIES = 5000


def entry_dict(entry: Any) -> dict[str, object]:
    return {
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "level": entry.level.value if entry.level else None,
        "thread": entry.thread,
        "logger": entry.logger,
        "message": entry.message,
        "raw": entry.raw,
    }


class LogsService:
    """Reads the core's log files. A day is read whole and cut here, so that following can ask
    for "what came after the n entries I have"."""

    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client

    def components(self) -> list[dict[str, object]]:
        logs = self._client().logs
        out = []
        for file in logs.list():
            data = file.to_dict()
            data["description"] = logs.get(file.component).description
            out.append(data)
        return out

    def days(self, component: str) -> list[str]:
        return list(self._client().logs.get(component).file().days)

    @staticmethod
    def _check(level: str | None, order: str) -> None:
        if level and level not in LEVELS:
            raise ValueError(f"level is {', '.join(LEVELS)}.")
        if order not in ("asc", "desc"):
            raise ValueError("order is asc or desc.")

    def entries(
        self,
        component: str,
        *,
        day: str | None,
        level: str | None,
        contains: str | None,
        order: str,
        limit: int,
        after: int | None,
    ) -> dict[str, object]:
        """Entries of a day. Without `after`, the latest `limit` of them; with it, the ones from
        position `after` on (what following asks for). `total` counts every entry that matches, in
        the order asked for."""
        self._check(level, order)
        log = self._client().logs.get(component)
        if not log.file(day).exists:
            return {"total": 0, "offset": 0, "items": [], "exists": False}
        found = log.read(day=day, level=level or None, contains=contains or None, order=order)
        total = len(found)
        limit = max(1, min(limit, MAX_ENTRIES))
        if after is None:
            # Newest first starts at the top; oldest first starts at the end of the file.
            offset = 0 if order == "desc" else max(total - limit, 0)
            window = found[:limit] if order == "desc" else found[offset:]
        else:
            offset = min(max(after, 0), total)
            window = found[offset : offset + MAX_ENTRIES]
        return {
            "total": total,
            "offset": offset,
            "items": [entry_dict(e) for e in window],
            "exists": True,
        }

    def export(
        self,
        component: str,
        *,
        day: str | None,
        level: str | None,
        contains: str | None,
        order: str,
    ) -> tuple[bytes, str]:
        self._check(level, order)
        log = self._client().logs.get(component)
        stamp = day or "today"
        with tempfile.TemporaryDirectory(prefix="vethuq-log-") as folder:
            target = Path(folder) / f"{component}-{stamp}.log"
            log.export(target, day=day, level=level or None, contains=contains or None, order=order)
            return target.read_bytes(), target.name
