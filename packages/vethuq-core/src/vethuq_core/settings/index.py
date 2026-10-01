"""Settings for the indexing run."""

from __future__ import annotations

import sqlite3

from vethuq_core.settings.settings import InvalidSettingValueError, Settings


class IndexSettings:
    THREAD_WORKERS_KEY = "index_thread_workers"
    DEFAULT_THREAD_WORKERS = "0"
    THREAD_WORKERS_AUTO = "auto"
    THREAD_WORKERS_MAX = 8
    STALE_LOCK_KEY = "index_stale_lock"
    DEFAULT_STALE_LOCK = "auto"
    STALE_LOCK_VALUES = ("enable", "disable", "auto")

    @staticmethod
    def get_thread_workers(conn: sqlite3.Connection) -> str:
        """How many worker threads background indexing uses. '0' (disabled) by default.

        One of '0' (disabled - sequential, single-threaded indexing), '1'-'8'
        (a fixed worker count), or 'auto' (sized at run time from current CPU/
        memory headroom - see `vethuq_core.ocr.resolve_thread_workers`).
        """
        value = Settings.get(conn, IndexSettings.THREAD_WORKERS_KEY)
        return value if value is not None else IndexSettings.DEFAULT_THREAD_WORKERS

    @staticmethod
    def set_thread_workers(conn: sqlite3.Connection, value: str) -> None:
        if value != IndexSettings.THREAD_WORKERS_AUTO:
            if not value.isdigit() or not 0 <= int(value) <= IndexSettings.THREAD_WORKERS_MAX:
                raise InvalidSettingValueError(
                    f"value must be 0-{IndexSettings.THREAD_WORKERS_MAX} "
                    f"or '{IndexSettings.THREAD_WORKERS_AUTO}'"
                )
        Settings.set(conn, IndexSettings.THREAD_WORKERS_KEY, value)

    @staticmethod
    def get_stale_lock(conn: sqlite3.Connection) -> str:
        """Whether a lock left behind by a run that didn't exit cleanly is auto-cleared
        on the next run. 'auto' by default.

        One of 'auto' (auto-clear - the default), 'enable' (auto-clear - an explicit
        opt-in with the same effect as 'auto'), or 'disable' (require `--force`, as before).
        """
        value = Settings.get(conn, IndexSettings.STALE_LOCK_KEY)
        return value if value is not None else IndexSettings.DEFAULT_STALE_LOCK

    @staticmethod
    def set_stale_lock(conn: sqlite3.Connection, value: str) -> None:
        if value not in IndexSettings.STALE_LOCK_VALUES:
            raise InvalidSettingValueError(
                f"value must be one of {IndexSettings.STALE_LOCK_VALUES}"
            )
        Settings.set(conn, IndexSettings.STALE_LOCK_KEY, value)
