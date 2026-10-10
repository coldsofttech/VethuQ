"""VethuQ's settings: `VethuQ().settings`."""

from __future__ import annotations

from vethuq._db import _Database
from vethuq._settings import _SourceSettings

__all__ = ["Settings", "SourceSettings"]


class SourceSettings:
    """Settings for sources.

    Not created directly: use `VethuQ().settings.sources`.
    """

    DEFAULT_REMOVED_RETENTION_MINUTES = _SourceSettings.DEFAULT_REMOVED_RETENTION_MINUTES

    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_removed_retention_minutes(self) -> int:
        """Minutes a removed source is kept before it is purged. 7 days unless changed."""
        with self._database.session() as session:
            return _SourceSettings.get_removed_retention_minutes(session)

    def set_removed_retention_minutes(self, minutes: int) -> None:
        """Keep removed sources for `minutes` before they are purged; 0 purges them at once.

        Raises `InvalidSettingValueError` if `minutes` isn't a whole number of 0 or more.
        """
        with self._database.session() as session:
            _SourceSettings.set_removed_retention_minutes(session, minutes)

    def reset_removed_retention_minutes(self) -> None:
        """Back to the default retention (7 days)."""
        with self._database.session() as session:
            _SourceSettings.reset_removed_retention_minutes(session)


class Settings:
    """VethuQ's settings, grouped by feature.

    Not created directly: use `VethuQ().settings`.
    """

    def __init__(self, database: _Database) -> None:
        self.sources = SourceSettings(database)
