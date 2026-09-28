"""Small persisted key-value settings store for VethuQ."""

from __future__ import annotations

import sqlite3

from vethuq_core.db import get_setting_value, upsert_setting

GPU_ENABLED_KEY = "gpu_enabled"
SEARCH_SNIPPET_CONTEXT_CHARS_KEY = "search_snippet_context_chars"
DEFAULT_SEARCH_SNIPPET_CONTEXT_CHARS = 80
REMOVED_SOURCE_RETENTION_MINUTES_KEY = "removed_source_retention_minutes"
DEFAULT_REMOVED_SOURCE_RETENTION_MINUTES = 7 * 24 * 60  # 7 days
OCR_RETRY_ATTEMPTS_KEY = "ocr_retry_attempts"
DEFAULT_OCR_RETRY_ATTEMPTS = 3
SEARCH_EXPORT_FORMAT_KEY = "search_export_format"
DEFAULT_SEARCH_EXPORT_FORMAT = "json"
SEARCH_EXPORT_FORMATS = ("json", "html")
THREAD_WORKERS_KEY = "thread_workers"
DEFAULT_THREAD_WORKERS = "0"
THREAD_WORKERS_AUTO = "auto"
THREAD_WORKERS_MAX = 8
STALE_LOCK_KEY = "stale_lock"
DEFAULT_STALE_LOCK = "auto"
STALE_LOCK_VALUES = ("enable", "disable", "auto")


class SettingsError(Exception):
    """Base class for settings errors."""


class InvalidSettingValueError(SettingsError, ValueError):
    """A setting value failed validation.

    Also a `ValueError` for backward compatibility with existing callers
    (e.g. the CLI) that already catch `ValueError` around the `set_*`
    functions below.
    """


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    return get_setting_value(conn, key)


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    upsert_setting(conn, key, value)


def is_gpu_enabled(conn: sqlite3.Connection) -> bool:
    """Whether OCR should attempt to use the GPU. Disabled by default."""
    return get_setting(conn, GPU_ENABLED_KEY) == "true"


def set_gpu_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    set_setting(conn, GPU_ENABLED_KEY, "true" if enabled else "false")


def get_search_snippet_context_chars(conn: sqlite3.Connection) -> int:
    """How many characters of context `search` shows around a match. 80 by default."""
    value = get_setting(conn, SEARCH_SNIPPET_CONTEXT_CHARS_KEY)
    return int(value) if value is not None else DEFAULT_SEARCH_SNIPPET_CONTEXT_CHARS


def set_search_snippet_context_chars(conn: sqlite3.Connection, chars: int) -> None:
    if chars < 0:
        raise InvalidSettingValueError("chars must be non-negative")
    set_setting(conn, SEARCH_SNIPPET_CONTEXT_CHARS_KEY, str(chars))


def get_removed_source_retention_minutes(conn: sqlite3.Connection) -> int:
    """Minutes a removed source is kept before it's purged from the DB. 7 days by default."""
    value = get_setting(conn, REMOVED_SOURCE_RETENTION_MINUTES_KEY)
    return int(value) if value is not None else DEFAULT_REMOVED_SOURCE_RETENTION_MINUTES


def set_removed_source_retention_minutes(conn: sqlite3.Connection, minutes: int) -> None:
    if minutes < 0:
        raise InvalidSettingValueError("minutes must be non-negative")
    set_setting(conn, REMOVED_SOURCE_RETENTION_MINUTES_KEY, str(minutes))


def get_ocr_retry_attempts(conn: sqlite3.Connection) -> int:
    """How many times to retry a file's OCR after a transient failure. 3 by default."""
    value = get_setting(conn, OCR_RETRY_ATTEMPTS_KEY)
    return int(value) if value is not None else DEFAULT_OCR_RETRY_ATTEMPTS


def set_ocr_retry_attempts(conn: sqlite3.Connection, attempts: int) -> None:
    if attempts < 0:
        raise InvalidSettingValueError("attempts must be non-negative")
    set_setting(conn, OCR_RETRY_ATTEMPTS_KEY, str(attempts))


def get_search_export_format(conn: sqlite3.Connection) -> str:
    """Default format `search --export` writes to when none is given. 'json' by default."""
    value = get_setting(conn, SEARCH_EXPORT_FORMAT_KEY)
    return value if value is not None else DEFAULT_SEARCH_EXPORT_FORMAT


def set_search_export_format(conn: sqlite3.Connection, format_: str) -> None:
    if format_ not in SEARCH_EXPORT_FORMATS:
        raise InvalidSettingValueError(f"format must be one of {SEARCH_EXPORT_FORMATS}")
    set_setting(conn, SEARCH_EXPORT_FORMAT_KEY, format_)


def get_thread_workers(conn: sqlite3.Connection) -> str:
    """How many worker threads background indexing uses. '0' (disabled) by default.

    One of '0' (disabled - sequential, single-threaded indexing), '1'-'8'
    (a fixed worker count), or 'auto' (sized at run time from current CPU/
    memory headroom - see `vethuq_core.ocr.resolve_thread_workers`).
    """
    value = get_setting(conn, THREAD_WORKERS_KEY)
    return value if value is not None else DEFAULT_THREAD_WORKERS


def set_thread_workers(conn: sqlite3.Connection, value: str) -> None:
    if value != THREAD_WORKERS_AUTO:
        if not value.isdigit() or not 0 <= int(value) <= THREAD_WORKERS_MAX:
            raise InvalidSettingValueError(
                f"value must be 0-{THREAD_WORKERS_MAX} or '{THREAD_WORKERS_AUTO}'"
            )
    set_setting(conn, THREAD_WORKERS_KEY, value)


def get_stale_lock(conn: sqlite3.Connection) -> str:
    """Whether a lock left behind by a run that didn't exit cleanly is auto-cleared
    on the next run. 'auto' by default.

    One of 'auto' (auto-clear - the default), 'enable' (auto-clear - an explicit
    opt-in with the same effect as 'auto'), or 'disable' (require `--force`, as before).
    """
    value = get_setting(conn, STALE_LOCK_KEY)
    return value if value is not None else DEFAULT_STALE_LOCK


def set_stale_lock(conn: sqlite3.Connection, value: str) -> None:
    if value not in STALE_LOCK_VALUES:
        raise InvalidSettingValueError(f"value must be one of {STALE_LOCK_VALUES}")
    set_setting(conn, STALE_LOCK_KEY, value)
