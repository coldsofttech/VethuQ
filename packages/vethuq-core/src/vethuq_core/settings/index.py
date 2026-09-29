"""Settings for the indexing run."""

from __future__ import annotations

from vethuq_core.settings.settings import InvalidSettingValueError, Settings
from vethuq_core.storage import Storage


class IndexSettings:
    THREAD_WORKERS_KEY = "index_thread_workers"
    DEFAULT_THREAD_WORKERS = "0"
    THREAD_WORKERS_AUTO = "auto"
    THREAD_WORKERS_MAX = 8
    STALE_LOCK_KEY = "index_stale_lock"
    DEFAULT_STALE_LOCK = "auto"
    STALE_LOCK_VALUES = ("enable", "disable", "auto")

    @staticmethod
    def get_thread_workers(storage: Storage) -> str:
        """How many worker threads background indexing uses. '0' (disabled) by default.

        One of '0' (disabled - sequential, single-threaded indexing), '1'-'8'
        (a fixed worker count), or 'auto' (sized at run time from current CPU/
        memory headroom - see `vethuq_core.ocr.Scheduler.resolve_workers`).
        """
        value = Settings.get(storage, IndexSettings.THREAD_WORKERS_KEY)
        return value if value is not None else IndexSettings.DEFAULT_THREAD_WORKERS

    @staticmethod
    def set_thread_workers(storage: Storage, value: str) -> None:
        if value != IndexSettings.THREAD_WORKERS_AUTO:
            if not value.isdigit() or not 0 <= int(value) <= IndexSettings.THREAD_WORKERS_MAX:
                raise InvalidSettingValueError(
                    f"value must be 0-{IndexSettings.THREAD_WORKERS_MAX} "
                    f"or '{IndexSettings.THREAD_WORKERS_AUTO}'"
                )
        Settings.set(storage, IndexSettings.THREAD_WORKERS_KEY, value)

    @staticmethod
    def get_stale_lock(storage: Storage) -> str:
        """Whether a lock left behind by a run that didn't exit cleanly is auto-cleared
        on the next run. 'auto' by default.

        One of 'auto' (auto-clear - the default), 'enable' (auto-clear - an explicit
        opt-in with the same effect as 'auto'), or 'disable' (require `--force`, as before).
        """
        value = Settings.get(storage, IndexSettings.STALE_LOCK_KEY)
        return value if value is not None else IndexSettings.DEFAULT_STALE_LOCK

    @staticmethod
    def set_stale_lock(storage: Storage, value: str) -> None:
        if value not in IndexSettings.STALE_LOCK_VALUES:
            raise InvalidSettingValueError(
                f"value must be one of {IndexSettings.STALE_LOCK_VALUES}"
            )
        Settings.set(storage, IndexSettings.STALE_LOCK_KEY, value)
