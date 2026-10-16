"""The add-on and bundle catalog: `VethuQ().catalog`.

The catalog is a signed list of every add-on and bundle that exists, with descriptions, so a person
can see what is available and not only what is installed here, and ask for it. It is fetched like
the policy (see `vethuq.policy`) and merged with what is installed.

    client.catalog.refresh()                  # look for a newer one (about once a day)
    for entry in client.catalog.addons():     # the catalog merged with what is installed
        print(entry.label, entry.state.value, entry.request_url)
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vethuq._catalog import (
    Catalog,
    CatalogAddon,
    CatalogBundle,
    CatalogResult,
    _CatalogClient,
)
from vethuq._db import _Database
from vethuq._logs import _PolicyLog
from vethuq._paths import _Paths
from vethuq._updates import _Versions
from vethuq.enums import AddonState, AddonStatus

if TYPE_CHECKING:
    from vethuq.addons import Addons
    from vethuq.policy import PolicyClient

__all__ = [
    "AddonState",
    "BundleEntry",
    "Catalog",
    "CatalogAddon",
    "CatalogBundle",
    "CatalogClient",
    "CatalogEntry",
    "CatalogResult",
]

_STATES = {
    AddonStatus.LOADED: AddonState.ENABLED,
    AddonStatus.DISABLED: AddonState.DISABLED,
    AddonStatus.INCOMPATIBLE: AddonState.INCOMPATIBLE,
    AddonStatus.FAILED: AddonState.FAILED,
}


@dataclass(frozen=True)
class CatalogEntry:
    """One add-on: what the catalog says about it, and where it stands on this computer."""

    id: str
    label: str
    summary: str
    state: AddonState
    description: str = ""
    kind: str = ""
    licence: str = ""  # "free", "licensed", or "" when the catalog doesn't say
    bundles: tuple[str, ...] = ()
    status: str = "available"  # available, coming_soon, deprecated
    listed: bool = True  # False for an installed add-on the catalog doesn't know
    installed_version: str | None = None
    min_client: str | None = None
    requires_newer_client: bool = False  # this VethuQ is older than `min_client`
    size_bytes: int | None = None
    docs_url: str | None = None
    request_url: str | None = None  # where to ask for it

    @property
    def installed(self) -> bool:
        return self.state is not AddonState.NOT_INSTALLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "description": self.description,
            "kind": self.kind,
            "licence": self.licence,
            "bundles": list(self.bundles),
            "status": self.status,
            "state": self.state.value,
            "installed": self.installed,
            "listed": self.listed,
            "installed_version": self.installed_version,
            "min_client": self.min_client,
            "requires_newer_client": self.requires_newer_client,
            "size_bytes": self.size_bytes,
            "docs_url": self.docs_url,
            "request_url": self.request_url,
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class BundleEntry:
    """One bundle, with how much of it is installed here."""

    id: str
    label: str
    summary: str
    addons: tuple[str, ...]
    installed: tuple[str, ...] = field(default_factory=tuple)  # of `addons`, the ones installed
    description: str = ""
    status: str = "available"
    docs_url: str | None = None
    request_url: str | None = None

    @property
    def complete(self) -> bool:
        """Whether every add-on of the bundle is installed."""
        return set(self.addons) <= set(self.installed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "description": self.description,
            "addons": list(self.addons),
            "installed": list(self.installed),
            "complete": self.complete,
            "status": self.status,
            "docs_url": self.docs_url,
            "request_url": self.request_url,
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class CatalogClient:
    """Reads and refreshes the catalog, and merges it with the installed add-ons.

    Not created directly: use `VethuQ().catalog`. Nothing is fetched on import, when the client is
    created or when this object is first used; only `refresh()` and `refresh_in_background()` use
    the network, only when the update check is not switched off, and none of the methods raises: a
    problem keeps the last good catalog, so offline use and local work are never blocked.
    """

    def __init__(
        self,
        database: _Database,
        policy: PolicyClient,
        addons: Callable[[], Addons],
        check_enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self._database = database
        self._policy = policy
        self._addons = addons
        self._check_enabled = check_enabled
        self._client: _CatalogClient | None = None
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        """The folder holding the cached catalog and its state (beside the policy's)."""
        return _Paths.policy_dir(self._database.db_path, create=False)

    def _catalog_client(self) -> _CatalogClient:
        with self._lock:
            if self._client is None:
                logger: logging.Logger = _PolicyLog.setup(self._database.db_path)
                self._client = _CatalogClient(
                    self.directory,
                    revoked=self._policy.revoked_key_ids,
                    enabled=self._check_enabled,
                    logger=logger,
                )
            return self._client

    def current(self) -> CatalogResult:
        """The catalog to use now: the cached one, else the built-in baseline. Makes no request."""
        return self._catalog_client().current()

    def refresh(self, force: bool = False) -> CatalogResult:
        """Check for a newer catalog and return the one to use.

        It asks at most about once a day (after a failed check, once an hour) unless `force` is
        true. While no policy keys are built into VethuQ, or the update check is off, it makes no
        request and returns `PolicyStatus.SKIPPED`.
        """
        return self._catalog_client().refresh(force=force)

    def refresh_in_background(self, force: bool = False) -> threading.Thread:
        """Run `refresh` on a daemon thread, so starting up is never delayed."""
        return self._catalog_client().refresh_in_background(force=force)

    # ----- merged with what is installed ------------------------------------------------------

    def addons(self, language: str | None = None) -> list[CatalogEntry]:
        """Every add-on in the catalog, then the installed ones it doesn't list, each with its state
        here. `language` (`es`, `es-MX`) picks the translated text where the catalog has it. Makes
        no request."""
        catalog = self.current().catalog
        installed = {info.id: info for info in self._addons().list()}
        try:
            running = _Versions.installed()
        except Exception:  # noqa: BLE001 - an unreadable version just means no comparison
            running = None
        entries: list[CatalogEntry] = []
        for listed in catalog.addons:
            item = listed.localized(language)
            info = installed.pop(item.id, None)
            entries.append(
                CatalogEntry(
                    id=item.id,
                    label=item.label,
                    summary=item.summary,
                    state=self._state(info),
                    description=item.description,
                    kind=item.kind,
                    licence=item.licence,
                    bundles=item.bundles,
                    status=item.status,
                    installed_version=info.version if info else None,
                    min_client=item.min_client,
                    requires_newer_client=_Versions.is_older(running, item.min_client),
                    size_bytes=item.size_bytes,
                    docs_url=item.docs_url,
                    request_url=item.request_url or catalog.request_url,
                )
            )
        entries.extend(
            CatalogEntry(
                id=info.id,
                label=info.name,
                summary="Installed here; not listed in the catalog.",
                state=self._state(info),
                listed=False,
                installed_version=info.version,
            )
            for info in installed.values()
        )
        return entries

    def bundles(self, language: str | None = None) -> list[BundleEntry]:
        """Every bundle in the catalog, with which of its add-ons are installed here."""
        catalog = self.current().catalog
        have = {info.id for info in self._addons().list()}
        found = []
        for listed in catalog.bundles:
            item = listed.localized(language)
            found.append(
                BundleEntry(
                    id=item.id,
                    label=item.label,
                    summary=item.summary,
                    addons=item.addons,
                    installed=tuple(a for a in item.addons if a in have),
                    description=item.description,
                    status=item.status,
                    docs_url=item.docs_url,
                    request_url=item.request_url or catalog.request_url,
                )
            )
        return found

    def get_addon(self, addon_id: str, language: str | None = None) -> CatalogEntry | None:
        """One add-on, or None if the catalog doesn't list it and it isn't installed."""
        return next((e for e in self.addons(language) if e.id == addon_id), None)

    def get_bundle(self, bundle_id: str, language: str | None = None) -> BundleEntry | None:
        return next((b for b in self.bundles(language) if b.id == bundle_id), None)

    @staticmethod
    def _state(info: Any) -> AddonState:
        if info is None:
            return AddonState.NOT_INSTALLED
        if info.disabled:
            return AddonState.DISABLED
        return _STATES.get(info.status, AddonState.FAILED)
