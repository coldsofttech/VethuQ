"""Finds installed add-ons and runs their hooks."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from vethuq._addons.finder import _AddonFinder
from vethuq._addons.host import _Host
from vethuq._addons.settings import _AddonSettingsStore
from vethuq._addons.tags import _WheelTags
from vethuq._credits import _Credits
from vethuq.enums import AddonStatus
from vethuq_addon_api import (
    API_VERSION,
    ENTRY_POINT_GROUP,
    Addon,
    CliGroup,
    FileTypeSpec,
    LanguageSpec,
    MigrationInfo,
    Normalizer,
    OcrEngineProvider,
    OcrPhaseSpec,
    SearchEngineSpec,
    TierSpec,
    WorkerScheduler,
)


@dataclass(frozen=True)
class _Loaded:
    id: str
    name: str
    version: str
    status: AddonStatus
    detail: str = ""
    addon: Addon | None = None


class _AddonManager:
    """Loads add-ons on first use. An add-on that is missing, incompatible or broken never stops
    VethuQ: it is listed with its status, and its hooks are skipped."""

    _logger = logging.getLogger("vethuq.addons")

    def __init__(
        self,
        db_path: Path,
        release_database: Callable[[], None],
        discover: Callable[[], Iterable[EntryPoint]] | None = None,
        credits: Callable[[], _Credits] | None = None,
    ) -> None:
        self._credits = credits
        self._db_path = Path(db_path)
        self._release = release_database
        self._discover = discover or self._installed
        self._loaded: dict[str, _Loaded] | None = None
        self._lock = threading.RLock()
        _AddonFinder.install()

    @staticmethod
    def _installed() -> Iterable[EntryPoint]:
        return entry_points(group=ENTRY_POINT_GROUP)

    # ----- loading --------------------------------------------------------------------------

    # The add-ons the user turned off are kept by VethuQ itself, as `addon.vethuq.disabled`.
    DISABLED_KEY = "disabled"

    def disabled_ids(self) -> set[str]:
        saved = _AddonSettingsStore(self._db_path, "vethuq").get(self.DISABLED_KEY, "") or ""
        return {item for item in saved.split(",") if item}

    def _load_one(
        self, point: EntryPoint, disabled: frozenset[str] | set[str] = frozenset()
    ) -> _Loaded:
        if point.name in disabled:
            dist = getattr(point, "dist", None)
            return _Loaded(
                point.name,
                dist.name if dist is not None else point.name,
                dist.version if dist is not None else "",
                AddonStatus.DISABLED,
                "turned off in settings",
            )
        dist = getattr(point, "dist", None)
        problem = _WheelTags.problem(dist)
        if problem is not None:
            # Not imported at all: a wrong-ABI extension would only say "No module named ...".
            self._logger.warning("Add-on %s can't run here: %s", point.name, problem)
            return _Loaded(
                point.name,
                dist.name if dist is not None else point.name,
                dist.version if dist is not None else "",
                AddonStatus.INCOMPATIBLE,
                problem,
            )
        try:
            cls = point.load()
            manifest = cls.manifest
        except Exception as exc:  # noqa: BLE001 - a broken add-on must not break VethuQ
            self._logger.warning("Couldn't load add-on %s", point.name, exc_info=True)
            where = self._where(dist)
            return _Loaded(point.name, point.name, "", AddonStatus.FAILED, f"{exc}{where}")
        if manifest.id != point.name:
            detail = f"its entry point is {point.name!r} but it declares id {manifest.id!r}"
            return _Loaded(point.name, manifest.name, manifest.version, AddonStatus.FAILED, detail)
        if not manifest.supports(API_VERSION):
            detail = (
                f"needs add-on API {manifest.api_min} to {manifest.api_max}; "
                f"this VethuQ provides {API_VERSION}"
            )
            return _Loaded(
                manifest.id, manifest.name, manifest.version, AddonStatus.INCOMPATIBLE, detail
            )
        try:
            addon = cls(_Host(manifest.id, self._db_path, self._release, credits=self._credits))
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Couldn't start add-on %s", manifest.id, exc_info=True)
            return _Loaded(
                manifest.id, manifest.name, manifest.version, AddonStatus.FAILED, f"{exc}"
            )
        return _Loaded(manifest.id, manifest.name, manifest.version, AddonStatus.LOADED, "", addon)

    @staticmethod
    def _where(dist: object) -> str:
        """` (in <folder>)` for a distribution that has a location, to say where the add-on is."""
        try:
            return f" (in {dist.locate_file('')})" if dist is not None else ""  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - only a hint
            return ""

    def loaded(self) -> dict[str, _Loaded]:
        with self._lock:
            if self._loaded is None:
                found: dict[str, _Loaded] = {}
                disabled = self.disabled_ids()
                for point in sorted(self._discover(), key=lambda p: p.name):
                    found.setdefault(point.name, self._load_one(point, disabled))
                self._loaded = found
            return self._loaded

    def reload(self) -> None:
        """Forget what was loaded; the next use looks again."""
        with self._lock:
            self._loaded = None

    def _collect(self, method: str) -> list:
        """What the running add-ons return from `method`, de-duplicated by `id` (the first add-on,
        by id, to offer an id wins). An add-on that fails when asked is logged and skipped."""
        found: dict[str, object] = {}
        for item in self.loaded().values():
            if item.addon is None:
                continue
            try:
                offered = list(getattr(item.addon, method)())
            except Exception:  # noqa: BLE001 - a broken add-on must not break VethuQ
                self._logger.warning("Add-on %s failed in %s", item.id, method, exc_info=True)
                continue
            for spec in offered:
                found.setdefault(spec.id, spec)
        return list(found.values())

    def language_specs(self) -> list[LanguageSpec]:
        """The languages the running add-ons provide, the system default first, then by id."""
        return sorted(self._collect("languages"), key=lambda spec: (not spec.default, spec.id))

    def file_type_specs(self) -> list[FileTypeSpec]:
        """The file types the running add-ons can read, by id."""
        return sorted(self._collect("file_types"), key=lambda spec: spec.id)

    def tier_specs(self) -> list[TierSpec]:
        """The processing tiers the running add-ons provide, by id."""
        return sorted(self._collect("processing_tiers"), key=lambda spec: spec.id)

    def search_engine_specs(self) -> list[SearchEngineSpec]:
        """The search engines the running add-ons provide, by id."""
        return sorted(self._collect("search_engines"), key=lambda spec: spec.id)

    def normalizer_list(self) -> list[Normalizer]:
        """The search normalizers the running add-ons provide, in the order they apply."""
        return sorted(self._collect("normalizers"), key=lambda n: (n.order, n.id))

    def ocr_engine_providers(self) -> list[OcrEngineProvider]:
        """The OCR engines the running add-ons provide, by id."""
        return sorted(self._collect("ocr_engines"), key=lambda provider: provider.id)

    def ocr_phase_specs(self) -> list[OcrPhaseSpec]:
        """The OCR phases the running add-ons provide, in the order they run."""
        return sorted(self._collect("ocr_phases"), key=lambda spec: (spec.order, spec.id))

    def licence_bundles(self) -> dict[str, tuple[str, ...]]:
        """`{add-on id: bundle ids}` for every running add-on whose licence also comes with a
        bundle (see `Addon.licence_bundles`)."""
        found: dict[str, tuple[str, ...]] = {}
        for item in sorted(self.loaded().values(), key=lambda i: i.id):
            if item.addon is None:
                continue
            try:
                bundles = tuple(item.addon.licence_bundles())
            except Exception:  # noqa: BLE001 - a broken add-on must not break VethuQ
                self._logger.warning("Add-on %s failed in licence_bundles", item.id, exc_info=True)
                continue
            if bundles:
                found[item.id] = bundles
        return found

    def cli_groups(self) -> list[tuple[str, CliGroup]]:
        """`(add-on id, command group)` of every running add-on that adds commands, by add-on id."""
        found = []
        for item in sorted(self.loaded().values(), key=lambda i: i.id):
            if item.addon is None:
                continue
            try:
                group = item.addon.cli()
            except Exception:  # noqa: BLE001 - a broken add-on must not break the CLI
                self._logger.warning("Add-on %s failed in cli", item.id, exc_info=True)
                continue
            if group is not None:
                found.append((item.id, group))
        return found

    def worker_scheduler(self) -> WorkerScheduler | None:
        """The worker scheduler of the first running add-on (by id) that offers one, if any."""
        for item in sorted(self.loaded().values(), key=lambda i: i.id):
            if item.addon is None:
                continue
            try:
                scheduler = item.addon.worker_scheduler()
            except Exception:  # noqa: BLE001 - a broken add-on must not break VethuQ
                self._logger.warning("Add-on %s failed in worker_scheduler", item.id, exc_info=True)
                continue
            if scheduler is not None:
                return scheduler
        return None

    # ----- hooks (the interface `_Database` calls) ------------------------------------------

    def _running(self) -> list[Addon]:
        return [item.addon for item in self.loaded().values() if item.addon is not None]

    def on_open(self) -> None:
        for addon in self._running():
            try:
                addon.on_open()
            except Exception:  # noqa: BLE001 - hooks are best effort
                self._logger.warning(
                    "Add-on %s failed in on_open", addon.manifest.id, exc_info=True
                )

    def before_migration(self, stored: int, target: int) -> None:
        info = MigrationInfo(self._db_path, stored, target)
        for addon in self._running():
            try:
                addon.before_migration(info)
            except Exception:  # noqa: BLE001
                self._logger.warning(
                    "Add-on %s failed in before_migration", addon.manifest.id, exc_info=True
                )
