"""Settings for `search` and its result export."""

from __future__ import annotations

import sqlite3

from vethuq_core.settings.settings import InvalidSettingValueError, Settings


class SearchSettings:
    SNIPPET_CONTEXT_CHARS_KEY = "search_snippet_context_chars"
    DEFAULT_SNIPPET_CONTEXT_CHARS = 80
    EXPORT_FORMAT_KEY = "search_export_format"
    DEFAULT_EXPORT_FORMAT = "json"
    EXPORT_FORMATS = ("json", "html")

    @staticmethod
    def get_snippet_context_chars(conn: sqlite3.Connection) -> int:
        """How many characters of context `search` shows around a match. 80 by default."""
        value = Settings.get(conn, SearchSettings.SNIPPET_CONTEXT_CHARS_KEY)
        return int(value) if value is not None else SearchSettings.DEFAULT_SNIPPET_CONTEXT_CHARS

    @staticmethod
    def set_snippet_context_chars(conn: sqlite3.Connection, chars: int) -> None:
        if chars < 0:
            raise InvalidSettingValueError("chars must be non-negative")
        Settings.set(conn, SearchSettings.SNIPPET_CONTEXT_CHARS_KEY, str(chars))

    @staticmethod
    def get_export_format(conn: sqlite3.Connection) -> str:
        """Default format `search --export` writes to when none is given. 'json' by default."""
        value = Settings.get(conn, SearchSettings.EXPORT_FORMAT_KEY)
        return value if value is not None else SearchSettings.DEFAULT_EXPORT_FORMAT

    @staticmethod
    def set_export_format(conn: sqlite3.Connection, format_: str) -> None:
        if format_ not in SearchSettings.EXPORT_FORMATS:
            raise InvalidSettingValueError(f"format must be one of {SearchSettings.EXPORT_FORMATS}")
        Settings.set(conn, SearchSettings.EXPORT_FORMAT_KEY, format_)
