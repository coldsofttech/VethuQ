"""The entry point: `vethuq.VethuQ()`."""

from __future__ import annotations

import threading
from pathlib import Path
from types import TracebackType

from vethuq._addons import _AddonManager
from vethuq._credits import _Credits
from vethuq._db import _Database
from vethuq._filetypes import _FileTypeCatalog
from vethuq._indexing import _Indexer
from vethuq._languages import _LanguageCatalog
from vethuq._maintenance import _Maintenance
from vethuq._metrics import _Metrics
from vethuq._ocr import _Models, _Ocr
from vethuq._paths import _Paths
from vethuq._tiers import _LocalExecutor, _Tiers
from vethuq.addons import Addons
from vethuq.credits import Credits
from vethuq.db import Db
from vethuq.file_types import FileTypes
from vethuq.index import Index
from vethuq.languages import Languages
from vethuq.logs import Logs
from vethuq.metrics import Metrics
from vethuq.ocr import Ocr
from vethuq.paths import Paths
from vethuq.policy import PolicyClient
from vethuq.settings import Settings
from vethuq.sources import Sources
from vethuq.stats import Stats
from vethuq.tiers import Tiers
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
        self._file_types: FileTypes | None = None
        self._index: Index | None = None
        self._ocr: Ocr | None = None
        self._ocr_runtime: _Ocr | None = None
        self._credit_service: _Credits | None = None
        self._metrics_service: _Metrics | None = None
        self._indexer: _Indexer | None = None
        self._credits: Credits | None = None
        self._metrics: Metrics | None = None
        self._stats: Stats | None = None
        self._tier_catalog: _Tiers | None = None
        self._tiers: Tiers | None = None
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

    def _catalog(self) -> _LanguageCatalog:
        return _LanguageCatalog(self._manager().language_specs)

    def _file_type_catalog(self) -> _FileTypeCatalog:
        return _FileTypeCatalog(self._manager().file_type_specs)

    def _runtime(self) -> _Ocr:
        manager = self._manager()
        with self._lock:
            if self._ocr_runtime is None:
                self._ocr_runtime = _Ocr(
                    manager.ocr_engine_providers,
                    manager.ocr_phase_specs,
                    lambda: _Paths.models_dir(self.db_path),
                )
            return self._ocr_runtime

    def _credit_engine(self) -> _Credits:
        db = self._db()
        with self._lock:
            if self._credit_service is None:
                self._credit_service = _Credits(
                    db, lambda: self.policy.current().policy.raw, self.version.vethuq
                )
            return self._credit_service

    def _metrics_engine(self) -> _Metrics:
        credits, db, version = self._credit_engine(), self._db(), self.version.vethuq
        with self._lock:
            if self._metrics_service is None:
                self._metrics_service = _Metrics(db, credits, version)
            return self._metrics_service

    def _tier_engine(self) -> _Tiers:
        runtime, manager = self._runtime(), self._manager()
        with self._lock:
            if self._tier_catalog is None:
                self._tier_catalog = _Tiers(manager.tier_specs, _LocalExecutor(runtime))
            return self._tier_catalog

    def _indexer_engine(self) -> _Indexer:
        credits, tiers = self._credit_engine(), self._tier_engine()
        db, types, manager = self._db(), self._file_type_catalog(), self._manager()
        with self._lock:
            if self._indexer is None:
                self._indexer = _Indexer(db, types, manager.language_specs, tiers, credits)
            return self._indexer

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
            self._sources = Sources(self._db(), self._catalog(), self._file_type_catalog())
        return self._sources

    @property
    def languages(self) -> Languages:
        """The languages VethuQ can read documents in."""
        if self._languages is None:
            self._languages = Languages(self._db(), self._catalog())
        return self._languages

    @property
    def file_types(self) -> FileTypes:
        """The kinds of file VethuQ can read."""
        if self._file_types is None:
            self._file_types = FileTypes(self._file_type_catalog())
        return self._file_types

    @property
    def index(self) -> Index:
        """Index sources: read their files into pages."""
        if self._index is None:
            self._index = Index(self._db(), self._indexer_engine(), self._metrics_engine())
        return self._index

    @property
    def tiers(self) -> Tiers:
        """The processing tiers: where pages that need OCR are read (local by default)."""
        if self._tiers is None:
            self._tiers = Tiers(self._db(), self._tier_engine())
        return self._tiers

    @property
    def credits(self) -> Credits:
        """What reading pages costs, and what you have left."""
        if self._credits is None:
            indexer = self._indexer_engine()
            tiers = self._tier_engine()

            def wallets() -> list[str]:
                return list(dict.fromkeys(v.wallet for v in tiers.views() if v.available))

            self._credits = Credits(self._db(), self._credit_engine(), indexer.estimate, wallets)
        return self._credits

    @property
    def stats(self) -> Stats:
        """Statistics about the work done: processing and confidence."""
        if self._stats is None:
            self._stats = Stats(self._db())
        return self._stats

    @property
    def metrics(self) -> Metrics:
        """Sharing anonymous usage metrics (off unless you opt in)."""
        if self._metrics is None:
            self._metrics = Metrics(self._db(), self._metrics_engine())
        return self._metrics

    @property
    def ocr(self) -> Ocr:
        """The OCR engines, phases and models."""
        if self._ocr is None:
            manager = self._manager()
            runtime = self._runtime()
            models = _Models(
                manager.ocr_engine_providers,
                manager.language_specs,
                lambda: [p.profile for p in manager.ocr_phase_specs() if p.profile],
                runtime.models_dir,
                runtime.forget,
            )
            self._ocr = Ocr(runtime, models)
        return self._ocr

    @property
    def settings(self) -> Settings:
        """VethuQ's settings."""
        if self._settings is None:
            self._settings = Settings(self._db(), self._catalog())
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
            self._file_types = None
            self._index = None
            self._ocr = None
            self._credit_service = None
            self._metrics_service = None
            self._indexer = None
            self._credits = None
            self._metrics = None
            self._stats = None
            self._github = None
            self._tier_catalog = None
            self._tiers = None

    def __enter__(self) -> VethuQ:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
