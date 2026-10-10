"""The add-on contract: what an add-on implements and what VethuQ gives it."""

from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

API_VERSION = "0.1"


def _parse(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


class Hook(StrEnum):
    """The points where VethuQ calls an add-on. Hooks are best effort: a failing hook is logged
    and never stops VethuQ."""

    ON_OPEN = "on_open"
    BEFORE_MIGRATION = "before_migration"


@dataclass(frozen=True)
class Manifest:
    """What an add-on declares about itself. `api_min`/`api_max` are the add-on API versions
    (`major.minor`) it works with."""

    id: str
    name: str
    version: str
    api_min: str = API_VERSION
    api_max: str = API_VERSION

    def supports(self, api_version: str = API_VERSION) -> bool:
        """Whether this add-on works with the given add-on API version."""
        try:
            return _parse(self.api_min) <= _parse(api_version) <= _parse(self.api_max)
        except ValueError:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "addon_api": {"min": self.api_min, "max": self.api_max},
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class MigrationInfo:
    """Passed to `before_migration`: the database is about to move from one schema to another."""

    db_path: Path
    from_version: int
    to_version: int


@runtime_checkable
class Host(Protocol):
    """What VethuQ offers an add-on. Each add-on gets its own host, so settings are its own."""

    @property
    def api_version(self) -> str: ...

    @property
    def app_version(self) -> str: ...

    @property
    def db_path(self) -> Path:
        """The database file."""

    @property
    def schema_version(self) -> int:
        """The schema version this VethuQ reads and writes."""

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """An add-on setting (kept in the VethuQ database, namespaced to this add-on)."""

    def set_setting(self, key: str, value: str) -> None: ...

    def reset_setting(self, key: str) -> None: ...

    def revoked_licence_ids(self) -> frozenset[str]:
        """Licence ids the signed policy has revoked (from the cached policy; no network)."""

    def addon_policy_enabled(self) -> bool:
        """False if the signed policy has switched this add-on off remotely."""

    def release_database(self) -> None:
        """Close VethuQ's connections to the database, e.g. before replacing the file."""

    def log(self, level: int, message: str) -> None: ...


class Addon(ABC):  # noqa: B024 - hooks are optional, so there is nothing abstract
    """Base class of an add-on. Register a subclass as the `vethuq.addons` entry point.

    VethuQ creates it with a `Host` when the first database is opened. Override the hooks you need.
    An add-on checks its own licence; VethuQ never tells it a licence is valid.
    """

    manifest: ClassVar[Manifest]

    def __init__(self, host: Host) -> None:
        self.host = host

    def on_open(self) -> None:
        """The database has been opened (schema ready, integrity checked)."""

    def before_migration(self, info: MigrationInfo) -> None:
        """The database is about to be migrated to a newer schema."""
