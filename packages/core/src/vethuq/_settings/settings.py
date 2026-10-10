"""The settings service: named values saved in the database, with defaults."""

from __future__ import annotations

from sqlalchemy.orm import Session

from vethuq._db import _Setting
from vethuq._errors import _InvalidSettingValueError


class _Settings:
    @staticmethod
    def get(session: Session, key: str) -> str | None:
        """The saved value of a setting, or None if it has none (its default applies)."""
        row = session.get(_Setting, key)
        return row.value if row is not None else None

    @staticmethod
    def set(session: Session, key: str, value: str) -> None:
        row = session.get(_Setting, key)
        if row is None:
            session.add(_Setting(key=key, value=value))
        else:
            row.value = value
        session.flush()

    @staticmethod
    def reset(session: Session, key: str) -> None:
        """Forget a setting's saved value so its default applies again."""
        row = session.get(_Setting, key)
        if row is not None:
            session.delete(row)
            session.flush()


class _SourceSettings:
    REMOVED_RETENTION_MINUTES_KEY = "index_removed_source_retention_minutes"
    DEFAULT_REMOVED_RETENTION_MINUTES = 7 * 24 * 60  # 7 days

    @staticmethod
    def get_removed_retention_minutes(session: Session) -> int:
        """Minutes a removed source is kept before it is purged. 7 days unless changed."""
        value = _Settings.get(session, _SourceSettings.REMOVED_RETENTION_MINUTES_KEY)
        default = _SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES
        try:
            return int(value) if value is not None else default
        except ValueError:
            return default

    @staticmethod
    def set_removed_retention_minutes(session: Session, minutes: int) -> None:
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            raise _InvalidSettingValueError(
                f"The retention must be a whole number of minutes, not {minutes!r}.",
                "Use 0 to purge removed sources at once.",
            )
        if minutes < 0:
            raise _InvalidSettingValueError(
                f"The retention can't be negative ({minutes}).",
                "Use 0 to purge removed sources at once.",
            )
        _Settings.set(session, _SourceSettings.REMOVED_RETENTION_MINUTES_KEY, str(minutes))

    @staticmethod
    def reset_removed_retention_minutes(session: Session) -> None:
        """Back to the default retention (7 days)."""
        _Settings.reset(session, _SourceSettings.REMOVED_RETENTION_MINUTES_KEY)
