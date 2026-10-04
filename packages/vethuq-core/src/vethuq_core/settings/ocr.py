"""Settings for OCR."""

from __future__ import annotations

from vethuq_core.settings.settings import InvalidSettingValueError, Settings
from vethuq_core.storage import Storage


class OcrSettings:
    RETRY_ATTEMPTS_KEY = "index_ocr_retry_attempts"
    DEFAULT_RETRY_ATTEMPTS = 3
    STABILITY_CHECK_SECONDS_KEY = "stability_check_seconds"
    DEFAULT_STABILITY_CHECK_SECONDS = 1.0
    ENGINE_KEY = "index_engine"
    DEFAULT_ENGINE = "quick"
    ENGINE_MODES = ("quick", "moderate", "deep")

    @staticmethod
    def get_retry_attempts(storage: Storage) -> int:
        """How many times to retry a file's OCR after a transient failure. 3 by default."""
        value = Settings.get(storage, OcrSettings.RETRY_ATTEMPTS_KEY)
        return int(value) if value is not None else OcrSettings.DEFAULT_RETRY_ATTEMPTS

    @staticmethod
    def set_retry_attempts(storage: Storage, attempts: int) -> None:
        if attempts < 0:
            raise InvalidSettingValueError("attempts must be non-negative")
        Settings.set(storage, OcrSettings.RETRY_ATTEMPTS_KEY, str(attempts))

    @staticmethod
    def reset_retry_attempts(storage: Storage) -> None:
        """Back to the default number of retries."""
        OcrSettings.set_retry_attempts(storage, OcrSettings.DEFAULT_RETRY_ATTEMPTS)

    @staticmethod
    def get_stability_check_seconds(storage: Storage) -> float:
        """Seconds between the two stats that confirm a file has stopped changing before
        it's indexed. 1 by default; 0 disables the check."""
        value = Settings.get(storage, OcrSettings.STABILITY_CHECK_SECONDS_KEY)
        return float(value) if value is not None else OcrSettings.DEFAULT_STABILITY_CHECK_SECONDS

    @staticmethod
    def set_stability_check_seconds(storage: Storage, seconds: float) -> None:
        if seconds < 0:
            raise InvalidSettingValueError("seconds must be non-negative")
        Settings.set(storage, OcrSettings.STABILITY_CHECK_SECONDS_KEY, str(seconds))

    @staticmethod
    def reset_stability_check_seconds(storage: Storage) -> None:
        """Back to the default stability check."""
        OcrSettings.set_stability_check_seconds(
            storage, OcrSettings.DEFAULT_STABILITY_CHECK_SECONDS
        )

    @staticmethod
    def get_engine(storage: Storage) -> str:
        """How thoroughly OCR looks for rotated text. 'quick' by default.

        One of 'quick' (upright text only - the fastest), 'moderate' (also 90/180/
        270 degrees), or 'deep' (also every 15 degrees in between). Each mode
        includes the ones before it: everything is indexed 'quick' first so it's
        searchable right away, then the deeper passes run in the background - see
        `vethuq_core.ocr.Deepening.PHASE_ANGLES`.
        """
        value = Settings.get(storage, OcrSettings.ENGINE_KEY)
        return value if value is not None else OcrSettings.DEFAULT_ENGINE

    @staticmethod
    def set_engine(storage: Storage, value: str) -> None:
        if value not in OcrSettings.ENGINE_MODES:
            raise InvalidSettingValueError(f"value must be one of {OcrSettings.ENGINE_MODES}")
        Settings.set(storage, OcrSettings.ENGINE_KEY, value)

    @staticmethod
    def reset_engine(storage: Storage) -> None:
        """Back to the default engine mode."""
        OcrSettings.set_engine(storage, OcrSettings.DEFAULT_ENGINE)
