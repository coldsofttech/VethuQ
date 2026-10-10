"""Housekeeping done each time the database is opened."""

from __future__ import annotations

from sqlalchemy.orm import Session

from vethuq._settings import _SourceSettings
from vethuq._sources import _Sources


class _Maintenance:
    @staticmethod
    def on_open(session: Session) -> None:
        """Permanently delete the sources that were removed longer ago than the retention."""
        retention = _SourceSettings.get_removed_retention_minutes(session)
        _Sources.purge_expired(session, retention)
