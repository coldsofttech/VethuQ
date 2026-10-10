"""The public view of installed add-ons."""

from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vethuq._addons import _AddonManager, _AddonSettingsStore
from vethuq.enums import AddonStatus

__all__ = ["AddonInfo", "AddonSettings", "Addons"]


@dataclass(frozen=True)
class AddonInfo:
    """One installed add-on and whether it is running."""

    id: str
    name: str
    version: str
    status: AddonStatus
    detail: str = ""  # why it isn't running

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "detail": self.detail,
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
        self, db_path: Path, manager: _AddonManager, open_database: Callable[[], None]
    ) -> None:
        self._db_path = db_path
        self._open_database = open_database
        self._manager = manager

    def list(self) -> list[AddonInfo]:
        """Every installed add-on, by id, with whether it is running."""
        return [
            AddonInfo(item.id, item.name, item.version, item.status, item.detail)
            for item in self._manager.loaded().values()
        ]

    def get(self, addon_id: str) -> AddonInfo | None:
        """One installed add-on, or None if it isn't installed."""
        return next((info for info in self.list() if info.id == addon_id), None)

    def is_installed(self, addon_id: str) -> bool:
        return self.get(addon_id) is not None

    def settings(self, addon_id: str) -> AddonSettings:
        """The settings of one add-on."""
        return AddonSettings(_AddonSettingsStore(self._db_path, addon_id), self._open_database)

    def reload(self) -> None:
        """Look for installed add-ons again (after installing one in a running process)."""
        self._manager.reload()
