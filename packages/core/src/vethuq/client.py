"""The entry point: `vethuq.VethuQ()`."""

from __future__ import annotations

import threading
from pathlib import Path
from types import TracebackType

from vethuq._addons import _AddonManager
from vethuq._db import _Database
from vethuq._maintenance import _Maintenance
from vethuq.addons import Addons
from vethuq.db import Db
from vethuq.languages import Languages
from vethuq.logs import Logs
from vethuq.paths import Paths
from vethuq.policy import PolicyClient
from vethuq.settings import Settings
from vethuq.sources import Sources
from vethuq.updates import Updates
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
        self._policy: PolicyClient | None = None
        self._updates: Updates | None = None
        self._checks: Db | None = None
        self._addon_manager: _AddonManager | None = None
        self._addons: Addons | None = None
        self._lock = threading.Lock()

    @property
    def db_path(self) -> Path:
        """The database file this client uses."""
        return self._db_path or Paths.db_path()

    def _manager(self) -> _AddonManager:
        with self._lock:
            if self._addon_manager is None:
                self._addon_manager = _AddonManager(self.db_path, self._release_database)
            return self._addon_manager

    def _release_database(self) -> None:
        """Close the connections (used by add-ons, e.g. before replacing the database file)."""
        database = self._database
        if database is not None:
            database.dispose()

    def _db(self) -> _Database:
        manager = self._manager()
        with self._lock:
            if self._database is None:
                self._database = _Database(
                    self.db_path, on_open=_Maintenance.on_open, hooks=manager
                )
            return self._database

    def _open_database(self) -> None:
        """Open the database (create it on first use) if it isn't open yet."""
        with self._db().session():
            pass

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
    def policy(self) -> PolicyClient:
        """The signed policy: versions, notices and feature flags."""
        if self._policy is None:
            self._policy = PolicyClient(self._db())
        return self._policy

    @property
    def db(self) -> Db:
        """Checks on the database file, such as the integrity check."""
        if self._checks is None:
            self._checks = Db(self._db())
        return self._checks

    @property
    def updates(self) -> Updates:
        """Whether a newer VethuQ exists, and which features need one."""
        if self._updates is None:
            self._updates = Updates(self._db(), self.policy)
        return self._updates

    @property
    def addons(self) -> Addons:
        """The add-ons installed next to VethuQ. It doesn't open the database."""
        if self._addons is None:
            self._addons = Addons(self.db_path, self._manager(), self._open_database)
        return self._addons

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
            self._policy = None
            self._updates = None
            self._checks = None
            self._addons = None

    def __enter__(self) -> VethuQ:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
