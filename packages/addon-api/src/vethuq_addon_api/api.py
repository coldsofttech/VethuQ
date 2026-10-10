"""The add-on contract: what an add-on implements and what VethuQ gives it."""

from __future__ import annotations

import json
from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

# The version of this contract, `major.minor.patch`. Add-ons declare the range they work with; a
# breaking change raises the major (or the minor while it is 0), a compatible addition the minor.
API_VERSION = "0.2.0"


def _parse(version: str) -> tuple[int, ...]:
    """`1.2` and `1.2.0` are the same version."""
    parts = tuple(int(part) for part in version.split("."))
    return parts + (0,) * (3 - len(parts))


class Hook(StrEnum):
    """The points where VethuQ calls an add-on. Hooks are best effort: a failing hook is logged
    and never stops VethuQ."""

    ON_OPEN = "on_open"
    BEFORE_MIGRATION = "before_migration"


@dataclass(frozen=True)
class Manifest:
    """What an add-on declares about itself. `api_min`/`api_max` are the add-on API versions
    (`major.minor.patch`) it works with."""

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


@dataclass(frozen=True)
class LanguageSpec:
    """A language an add-on lets VethuQ read documents in.

    `id` is the short code users pass around (`"en"`). `default` marks the system default
    language: the one every install has, and the fallback when nothing else is usable. A language
    that exists but can't be used right now (for instance its licence has lapsed) is returned with
    `available=False` and a `reason`. `ocr` holds what OCR will need later (engine language codes,
    model names); VethuQ stores it and doesn't read it yet.
    """

    id: str
    label: str
    native_label: str = ""
    script: str = ""
    default: bool = False
    available: bool = True
    reason: str = ""
    ocr: Mapping[str, Any] = field(default_factory=dict)

    @property
    def display_label(self) -> str:
        """`Telugu (తెలుగు)`: the label with its native name beside it, when there is one."""
        return f"{self.label} ({self.native_label})" if self.native_label else self.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "native_label": self.native_label,
            "script": self.script,
            "default": self.default,
            "available": self.available,
            "reason": self.reason,
            "ocr": dict(self.ocr),
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


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

    def on_open(self) -> None:  # noqa: B027 - optional hook
        """The database has been opened (schema ready, integrity checked)."""

    def before_migration(self, info: MigrationInfo) -> None:  # noqa: B027 - optional hook
        """The database is about to be migrated to a newer schema."""

    def languages(self) -> list[LanguageSpec]:
        """The languages this add-on provides (none, unless it is a language add-on).

        Called when VethuQ needs to know what it can read; return the same languages each time,
        marking one `available=False` rather than leaving it out when it can't be used."""
        return []
