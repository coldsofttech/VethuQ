"""The public view of installed add-ons."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vethuq._addons import _AddonManager, _AddonSettingsStore
from vethuq.enums import AddonStatus
from vethuq_addon_api import CliGroup

if TYPE_CHECKING:
    from vethuq.catalog import BundleEntry, CatalogClient, CatalogEntry

__all__ = ["AddonInfo", "AddonSettings", "Addons"]


@dataclass(frozen=True)
class AddonInfo:
    """One installed add-on and whether it is running."""

    id: str
    name: str
    version: str
    status: AddonStatus
    detail: str = ""  # why it isn't running
    disabled: bool = False  # turned off; it stops running at the next start

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "detail": self.detail,
            "disabled": self.disabled,
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class AddonSettings:
    """One add-on's settings, kept in the VethuQ database under `addon.<id>.<name>`."""

    def __init__(self, store: _AddonSettingsStore, open_database: Callable[[], None]) -> None:
        self._store = store
        self._open_database = open_database

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._store.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Save a value. Opens the VethuQ database first if it isn't open yet."""
        self._open_database()
        self._store.set(key, value)

    def reset(self, key: str) -> None:
        """Forget a saved value so the add-on's default applies again."""
        self._open_database()
        self._store.reset(key)


class Addons:
    """The add-ons installed next to VethuQ.

    Not created directly: use `VethuQ().addons`. Nothing is imported until you ask.
    """

    def __init__(
        self,
        db_path: Path,
        manager: _AddonManager,
        open_database: Callable[[], None],
        catalog: Callable[[], CatalogClient] | None = None,
    ) -> None:
        self._db_path = db_path
        self._open_database = open_database
        self._manager = manager
        self._catalog = catalog

    def list(self) -> list[AddonInfo]:
        """Every installed add-on, by id, with whether it is running."""
        turned_off = self._manager.disabled_ids()
        return [
            AddonInfo(
                item.id, item.name, item.version, item.status, item.detail, item.id in turned_off
            )
            for item in self._manager.loaded().values()
        ]

    def get(self, addon_id: str) -> AddonInfo | None:
        """One installed add-on, or None if it isn't installed."""
        return next((info for info in self.list() if info.id == addon_id), None)

    def catalog(self, language: str | None = None) -> list[CatalogEntry]:
        """Every add-on that exists, installed or not, with its description and where it stands on
        this computer (see `VethuQ().catalog`). Makes no request."""
        return self._catalog_client().addons(language)

    def bundles(self, language: str | None = None) -> list[BundleEntry]:
        """Every bundle of add-ons, with which of them are installed here."""
        return self._catalog_client().bundles(language)

    def _catalog_client(self) -> CatalogClient:
        if self._catalog is None:
            raise RuntimeError("This Addons has no catalog; use VethuQ().addons.")
        return self._catalog()

    def is_installed(self, addon_id: str) -> bool:
        return self.get(addon_id) is not None

    # An add-on VethuQ cannot do without: the fallback language.
    ALWAYS_ON = ("english",)

    def set_enabled(self, addon_id: str, enabled: bool) -> AddonInfo:
        """Turn an installed add-on off or on. The change applies the next time VethuQ starts (what
        is running keeps running), and `AddonInfo.disabled` says what is saved. Raises `ValueError`
        for an add-on that isn't installed, or one that can't be turned off."""
        info = self.get(addon_id)
        if info is None:
            raise ValueError(f"No add-on {addon_id!r} is installed.")
        if not enabled and addon_id in self.ALWAYS_ON:
            raise ValueError(f"{addon_id} can't be turned off: VethuQ needs it.")
        off = self._manager.disabled_ids()
        off.discard(addon_id) if enabled else off.add(addon_id)
        self._open_database()
        store = _AddonSettingsStore(self._db_path, "vethuq")
        if off:
            store.set(self._manager.DISABLED_KEY, ",".join(sorted(off)))
        else:
            store.reset(self._manager.DISABLED_KEY)
        return self.get(addon_id) or info

    def settings(self, addon_id: str) -> AddonSettings:
        """The settings of one add-on."""
        return AddonSettings(_AddonSettingsStore(self._db_path, addon_id), self._open_database)

    def cli(self) -> list[tuple[str, CliGroup]]:
        """`(add-on id, command group)` of every running add-on that adds commands to the `vethuq`
        command line (see `Addon.cli()`)."""
        return self._manager.cli_groups()

    def reload(self) -> None:
        """Look for installed add-ons again (after installing one in a running process)."""
        self._manager.reload()
