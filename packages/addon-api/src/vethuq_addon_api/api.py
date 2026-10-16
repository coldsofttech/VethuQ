"""The add-on contract: what an add-on implements and what VethuQ gives it."""

from __future__ import annotations

import json
from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from vethuq_addon_api.cli import CliGroup
    from vethuq_addon_api.ocr import OcrEngineProvider
    from vethuq_addon_api.readers import FileTypeSpec
    from vethuq_addon_api.scheduling import WorkerScheduler
    from vethuq_addon_api.search import Normalizer, SearchEngineSpec
    from vethuq_addon_api.tiers import TierSpec

# The version of this contract, `major.minor.patch`. Add-ons declare the range they work with; a
# breaking change raises the major (or the minor while it is 0), a compatible addition the minor.
API_VERSION = "0.11.0"


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

    `script_ranges` are the inclusive `(first, last)` code points of the language's writing system
    (`(0x0C00, 0x0C7F)` for Telugu). VethuQ tells which language a piece of text is written in by
    them, for example to mark up a Telugu run inside an English page in an HTML export so a browser
    picks the right font. A language with none is never recognised by its text.
    """

    id: str
    label: str
    native_label: str = ""
    script: str = ""
    default: bool = False
    available: bool = True
    reason: str = ""
    ocr: Mapping[str, Any] = field(default_factory=dict)
    script_ranges: tuple[tuple[int, int], ...] = ()

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
            "script_ranges": [list(r) for r in self.script_ranges],
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class OcrPhaseSpec:
    """A phase of OCR an add-on provides.

    Phases run in `order`; the first (`quick`) reads every page upright so a file is searchable
    fast. `angles` are the rotations, in degrees, the phase reads; `profile` names the OCR model
    set it uses (for example `mobile`).
    """

    id: str
    label: str
    order: int
    angles: tuple[int, ...] = (0,)
    profile: str = ""
    available: bool = True
    reason: str = ""


@runtime_checkable
class Credits(Protocol):
    """An add-on's own credits (its sub-wallet): for work that costs compute, such as embedding
    pages for semantic search. They can't be spent on anything else, and OCR credits can't be
    spent here."""

    def rate(self, key: str, default: float) -> float:
        """A price from the signed rate card (`semantic` is credits per page embedded), or
        `default` when the policy doesn't set one."""

    def balance_milli(self) -> int:
        """What can be spent now, in milli-credits (a credit is 1000), grace included."""

    def charge(self, amount_milli: int, *, note: str = "") -> None:
        """Spend `amount_milli`. Raises `CreditsExhaustedError` if there isn't enough, spending
        nothing."""


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

    @property
    def credits(self) -> Credits:
        """This add-on's credits (its sub-wallet)."""

    def data_dir(self) -> Path:
        """A folder of the add-on's own for files it keeps beside the database (created if
        missing). Nothing in it is VethuQ's: the add-on owns its layout and its migrations."""

    def revoked_licence_ids(self) -> frozenset[str]:
        """Licence ids the signed policy has revoked, and the signing key ids it has revoked (from
        the cached policy; no network). Pass the whole set as `Licences.verify(revoked=...)`: a
        licence on it, or signed by a key on it, stops verifying."""

    def licence_tokens(self) -> dict[str, str]:
        """The licence tokens installed for add-ons (their `licence` setting), by add-on id.
        For a tier that reads pages somewhere else, so the licences can be checked there; never
        write them to a log or send them anywhere that isn't encrypted for that purpose."""

    def addon_policy_enabled(self) -> bool:
        """False if the signed policy has switched this add-on off remotely."""

    def trusted_now(self) -> datetime:
        """The time to check a licence's validity against: the local clock corrected by the
        offset seen at the last policy fetch, and never earlier than the cached policy was issued,
        so setting the clock back does not revive an expired licence (pass it as
        `Licences.verify(now=...)`). The local clock when no policy was ever fetched. No network.
        An add-on written for an older VethuQ may find this missing: use
        `getattr(host, "trusted_now", None)`."""

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

    def file_types(self) -> list[FileTypeSpec]:
        """The file types this add-on can read (none, unless it is a file-type add-on)."""
        return []

    def ocr_engines(self) -> list[OcrEngineProvider]:
        """The OCR engines this add-on provides (none, unless it is an engine add-on)."""
        return []

    def ocr_phases(self) -> list[OcrPhaseSpec]:
        """The OCR phases this add-on provides (none, unless it is a phase add-on)."""
        return []

    def processing_tiers(self) -> list[TierSpec]:
        """The processing tiers this add-on provides (none, unless it is a tier add-on)."""
        return []

    def cli(self) -> CliGroup | None:
        """The commands and settings this add-on adds to the `vethuq` command line, or `None`.

        The group is mounted as `vethuq <group name> ...`, its settings under
        `vethuq settings addons <group name> ...`. Describe them with `CliGroup`; no CLI library is
        needed."""
        return None

    def licence_bundles(self) -> tuple[str, ...]:
        """The ids of the bundles whose licence also unlocks this add-on (`()` for an add-on that
        needs no licence, or is in no bundle). A licensed add-on checks its own licence and accepts
        one that lists the add-on or any of these; VethuQ asks so that one bundle licence can be
        installed on every add-on in the bundle."""
        return ()

    def worker_scheduler(self) -> WorkerScheduler | None:
        """A scheduler that sets how many files are read at once, or `None` (the default).

        Asked when a run starts with `workers` set to `auto`. Return `None` when the add-on is not
        licensed or is switched off; VethuQ then uses its static estimate."""
        return None

    def search_engines(self) -> list[SearchEngineSpec]:
        """The search engines this add-on provides (none, unless it is a search engine add-on)."""
        return []

    def normalizers(self) -> list[Normalizer]:
        """The search normalizers this add-on provides (none, unless it is a normalizer add-on)."""
        return []

    def languages(self) -> list[LanguageSpec]:
        """The languages this add-on provides (none, unless it is a language add-on).

        Called when VethuQ needs to know what it can read; return the same languages each time,
        marking one `available=False` rather than leaving it out when it can't be used."""
        return []
