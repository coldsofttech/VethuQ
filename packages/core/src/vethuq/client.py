"""The entry point: `vethuq.VethuQ()`."""

from __future__ import annotations

import threading
from pathlib import Path
from types import TracebackType

from vethuq._db import _Database
from vethuq.paths import Paths
from vethuq.sources import Sources

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

    def close(self) -> None:
        """Release the database connections. The client reconnects if used again."""
        with self._lock:
            if self._database is not None:
                self._database.dispose()
            self._database = None
            self._sources = None

    def __enter__(self) -> VethuQ:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
