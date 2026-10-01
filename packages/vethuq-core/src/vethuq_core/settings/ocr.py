"""Settings for OCR."""

from __future__ import annotations

import sqlite3

from vethuq_core.settings.settings import InvalidSettingValueError, Settings


class OcrSettings:
    RETRY_ATTEMPTS_KEY = "index_ocr_retry_attempts"
    DEFAULT_RETRY_ATTEMPTS = 3
    ENGINE_KEY = "index_engine"
    DEFAULT_ENGINE = "quick"
    ENGINE_MODES = ("quick", "moderate", "deep")

    @staticmethod
    def get_retry_attempts(conn: sqlite3.Connection) -> int:
        """How many times to retry a file's OCR after a transient failure. 3 by default."""
        value = Settings.get(conn, OcrSettings.RETRY_ATTEMPTS_KEY)
        return int(value) if value is not None else OcrSettings.DEFAULT_RETRY_ATTEMPTS

    @staticmethod
    def set_retry_attempts(conn: sqlite3.Connection, attempts: int) -> None:
        if attempts < 0:
            raise InvalidSettingValueError("attempts must be non-negative")
        Settings.set(conn, OcrSettings.RETRY_ATTEMPTS_KEY, str(attempts))

    @staticmethod
    def get_engine(conn: sqlite3.Connection) -> str:
        """How thoroughly OCR looks for rotated text. 'quick' by default.

        One of 'quick' (upright text only - the fastest), 'moderate' (also 90/180/
        270 degrees), or 'deep' (also every 15 degrees in between). Each mode
        includes the ones before it: everything is indexed 'quick' first so it's
        searchable right away, then the deeper passes run in the background - see
        `vethuq_core.ocr.Deepening.PHASE_ANGLES`.
        """
        value = Settings.get(conn, OcrSettings.ENGINE_KEY)
        return value if value is not None else OcrSettings.DEFAULT_ENGINE

    @staticmethod
    def set_engine(conn: sqlite3.Connection, value: str) -> None:
        if value not in OcrSettings.ENGINE_MODES:
            raise InvalidSettingValueError(f"value must be one of {OcrSettings.ENGINE_MODES}")
        Settings.set(conn, OcrSettings.ENGINE_KEY, value)
