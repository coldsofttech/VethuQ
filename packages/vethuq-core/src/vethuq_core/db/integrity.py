"""`PRAGMA integrity_check` support - detects on-disk database corruption early.

Run automatically when the database is opened (throttled by
`DbSettings.get_integrity_check`/`get_integrity_check_interval_minutes`, so
it doesn't add a full database scan to every command) and on demand via
`vethuq db integrity-check`, so a database damaged by a crash or disk issue is
reported clearly instead of failing later with a confusing
`sqlite3.DatabaseError` mid-command.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from vethuq_core.db.queries import Integrity as IntegrityQuery
from vethuq_core.settings import DbSettings, Settings

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntegrityCheckResult:
    ok: bool
    errors: list[str]


class IntegrityCheck:
    LAST_RUN_AT_KEY = "integrity_check_last_run_at"

    @staticmethod
    def run(conn: sqlite3.Connection) -> IntegrityCheckResult:
        """Run `PRAGMA integrity_check` now and log the outcome.

        A clean database reports a single "ok" row; anything else is one or
        more specific corruption messages from SQLite itself (a bad page, a
        broken index, etc.), logged in full so it's actionable.
        """
        messages = IntegrityQuery.run_pragma(conn)
        ok = messages == ["ok"]
        if ok:
            _logger.info("Database integrity check passed")
        else:
            _logger.error("Database integrity check failed: %s", "; ".join(messages))
        Settings.set(conn, IntegrityCheck.LAST_RUN_AT_KEY, datetime.now(UTC).isoformat())
        return IntegrityCheckResult(ok=ok, errors=[] if ok else messages)

    @staticmethod
    def maybe_run(conn: sqlite3.Connection) -> IntegrityCheckResult | None:
        """Run the integrity check on connect, if `integrity_check` calls for it now.

        'disable' never runs it here (still available on demand via `run`);
        'enable' runs it on every connection; 'auto' (the default) runs it only
        once the configured interval has elapsed since the last run, tracked via
        a stored timestamp.
        """
        mode = DbSettings.get_integrity_check(conn)
        if mode == "disable":
            return None
        if mode == "auto":
            last_run_at = Settings.get(conn, IntegrityCheck.LAST_RUN_AT_KEY)
            if last_run_at is not None:
                interval = DbSettings.get_integrity_check_interval_minutes(conn)
                elapsed = datetime.now(UTC) - datetime.fromisoformat(last_run_at)
                if elapsed < timedelta(minutes=interval):
                    return None
        return IntegrityCheck.run(conn)
