"""`PRAGMA integrity_check`: detecting on-disk database corruption early.

Runs by itself when the database is opened (see `IntegrityCheckMode`; by default at most once per
interval, so it doesn't add a full scan to every start) and on demand. It uses its own plain
SQLite connection, not the SQLAlchemy engine, so it still works on a database the engine
can't open, and it reads its settings and saves its result straight from the `settings` table.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from vethuq.enums import IntegrityCheckMode


@dataclass(frozen=True)
class IntegrityCheckResult:
    """The outcome of an integrity check."""

    ok: bool
    errors: tuple[str, ...]  # SQLite's own messages (a bad page, a broken index, ...); empty if ok
    checked_at: datetime  # UTC
    quick: bool = False  # a quick check skips verifying that index contents match their tables

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "checked_at": self.checked_at.isoformat(),
            "quick": self.quick,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def from_json(text: str | None) -> IntegrityCheckResult | None:
        """A saved result, or None if there is none or it can't be read."""
        try:
            data = json.loads(text) if text else None
            if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
                return None
            errors = data.get("errors")
            checked_at = datetime.fromisoformat(data["checked_at"])
            return IntegrityCheckResult(
                ok=data["ok"],
                errors=tuple(str(e) for e in errors) if isinstance(errors, list) else (),
                checked_at=checked_at if checked_at.tzinfo else checked_at.replace(tzinfo=UTC),
                quick=data.get("quick") is True,
            )
        except (ValueError, TypeError, KeyError):
            return None


class _IntegrityCheck:
    MODE_KEY = "db_integrity_check"
    DEFAULT_MODE = IntegrityCheckMode.AUTO
    INTERVAL_KEY = "db_integrity_check_interval_minutes"
    DEFAULT_INTERVAL_MINUTES = 24 * 60  # 1 day
    RESULT_KEY = "integrity_check_last_result"
    BUSY_TIMEOUT_SECONDS = 5.0

    _logger = logging.getLogger("vethuq.database")

    # ----- the settings table, read and written directly ----------------------------------

    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        return sqlite3.connect(db_path, timeout=_IntegrityCheck.BUSY_TIMEOUT_SECONDS)

    @staticmethod
    def read_setting(db_path: Path, key: str) -> str | None:
        """A raw settings-table value; None if the database or the setting doesn't exist."""
        if not db_path.exists():
            return None
        try:
            conn = _IntegrityCheck._connect(db_path)
            try:
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return row[0] if row is not None else None

    @staticmethod
    def _write_setting(db_path: Path, key: str, value: str) -> None:
        """Save a settings-table value, if the database allows it (a damaged one may not)."""
        try:
            conn = _IntegrityCheck._connect(db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
                )
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            _IntegrityCheck._logger.warning("Could not save the integrity check result")

    @staticmethod
    def read_mode(db_path: Path) -> IntegrityCheckMode:
        value = _IntegrityCheck.read_setting(db_path, _IntegrityCheck.MODE_KEY)
        try:
            return IntegrityCheckMode(value) if value is not None else _IntegrityCheck.DEFAULT_MODE
        except ValueError:
            return _IntegrityCheck.DEFAULT_MODE

    @staticmethod
    def read_interval_minutes(db_path: Path) -> int:
        value = _IntegrityCheck.read_setting(db_path, _IntegrityCheck.INTERVAL_KEY)
        try:
            minutes = int(value) if value is not None else _IntegrityCheck.DEFAULT_INTERVAL_MINUTES
        except ValueError:
            return _IntegrityCheck.DEFAULT_INTERVAL_MINUTES
        return minutes if minutes >= 1 else _IntegrityCheck.DEFAULT_INTERVAL_MINUTES

    # ----- running it ---------------------------------------------------------------------

    @staticmethod
    def status(db_path: Path) -> IntegrityCheckResult | None:
        """The result of the last check, automatic or on demand; None if there hasn't been one."""
        return IntegrityCheckResult.from_json(
            _IntegrityCheck.read_setting(db_path, _IntegrityCheck.RESULT_KEY)
        )

    @staticmethod
    def run(
        db_path: Path, *, quick: bool = False, now: datetime | None = None
    ) -> IntegrityCheckResult:
        """Check the database file now, log the outcome, and save it.

        A clean database reports a single "ok" row; anything else is one or more specific
        messages from SQLite (a bad page, a broken index, ...), logged in full so they are
        actionable. A file SQLite can't read at all is reported as a failed check, not raised.
        """
        pragma = "quick_check" if quick else "integrity_check"
        started = time.monotonic()
        try:
            conn = _IntegrityCheck._connect(db_path)
            try:
                messages = [row[0] for row in conn.execute(f"PRAGMA {pragma}").fetchall()]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            messages = [str(exc)]
        ok = messages == ["ok"]
        seconds = time.monotonic() - started
        kind = "quick check" if quick else "integrity check"
        if ok:
            _IntegrityCheck._logger.info("Database %s passed (%.2fs)", kind, seconds)
        else:
            _IntegrityCheck._logger.error(
                "Database %s failed (%.2fs): %s", kind, seconds, "; ".join(messages)
            )
        result = IntegrityCheckResult(
            ok=ok,
            errors=() if ok else tuple(messages),
            checked_at=now or datetime.now(UTC),
            quick=quick,
        )
        _IntegrityCheck._write_setting(db_path, _IntegrityCheck.RESULT_KEY, result.to_json())
        return result

    @staticmethod
    def maybe_run(db_path: Path, now: datetime | None = None) -> IntegrityCheckResult | None:
        """Run the check on open, if the mode calls for it now.

        `DISABLE` never runs it here; `ENABLE` runs it every time; `AUTO` (the default) runs it
        unless a full check already passed within the interval. A check that failed is never
        counted as done, so a damaged database is checked again at the next open.
        """
        mode = _IntegrityCheck.read_mode(db_path)
        if mode is IntegrityCheckMode.DISABLE:
            return None
        moment = now or datetime.now(UTC)
        if mode is IntegrityCheckMode.AUTO:
            last = _IntegrityCheck.status(db_path)
            if last is not None and last.ok and not last.quick:
                interval = timedelta(minutes=_IntegrityCheck.read_interval_minutes(db_path))
                if moment - last.checked_at < interval:
                    return None
        return _IntegrityCheck.run(db_path, now=moment)
