"""The entry point: `vethuq.VethuQ()`."""

from __future__ import annotations

import threading
from pathlib import Path
from types import TracebackType

from vethuq._db import _Database
from vethuq.languages import Languages
from vethuq.logs import Logs
from vethuq.paths import Paths
from vethuq.settings import Settings
from vethuq.sources import Sources
from vethuq.version import VersionDetails

__all__ = ["VethuQ"]


class VethuQ:
    """A client for one VethuQ database.

        client = vethuq.VethuQ()
        client.sources.create("~/docs")

    `db_path` picks another database file (default: `vethuq.Paths.db_path()`). Use it as a
    context manager, or call `close()`, to release the database when finished.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path).expanduser() if db_path is not None else None
        self._database: _Database | None = None
        self._sources: Sources | None = None
        self._languages: Languages | None = None
        self._settings: Settings | None = None
        self._logs: Logs | None = None
        self._lock = threading.Lock()

    @property
    def db_path(self) -> Path:
        """The database file this client uses."""
        return self._db_path or Paths.db_path()

    def _db(self) -> _Database:
        with self._lock:
            if self._database is None:
                self._database = _Database(self.db_path)
            return self._database

    @property
    def sources(self) -> Sources:
        """Register and manage sources."""
        if self._sources is None:
            self._sources = Sources(self._db())
        return self._sources

    @property
    def languages(self) -> Languages:
        """The languages VethuQ can read documents in."""
        if self._languages is None:
            self._languages = Languages(self._db())
        return self._languages

    @property
    def settings(self) -> Settings:
        """VethuQ's settings."""
        if self._settings is None:
            self._settings = Settings(self._db())
        return self._settings

    @property
    def logs(self) -> Logs:
        """VethuQ's logs."""
        if self._logs is None:
            self._logs = Logs(self._db())
        return self._logs

    @property
    def version(self) -> VersionDetails:
        """What this install is running. It doesn't open the database."""
        return VersionDetails._collect()

    def close(self) -> None:
        """Release the database connections. The client reconnects if used again."""
        with self._lock:
            if self._database is not None:
                self._database.dispose()
            self._database = None
            self._sources = None
            self._languages = None
            self._settings = None
            self._logs = None

    def __enter__(self) -> VethuQ:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
