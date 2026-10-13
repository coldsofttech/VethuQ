"""What this install is running: `VethuQ().version`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vethuq._version import _Version

if TYPE_CHECKING:
    from vethuq._addons import _AddonManager

__all__ = ["Version"]


@dataclass(frozen=True)
class Version:
    """What this install is running: VethuQ, Python, the platform and the database schema.

    The last six fields list what is installed, by id, sorted: the file types, search engines,
    OCR engines and OCR languages the running add-ons provide, the running add-ons themselves,
    and the bundles.
    """

    vethuq: str
    python: str
    platform: str
    db_schema: int
    file_types: tuple[str, ...] = ()
    search_engines: tuple[str, ...] = ()
    ocr_engines: tuple[str, ...] = ()
    ocr_languages: tuple[str, ...] = ()
    add_ons: tuple[str, ...] = ()
    bundles: tuple[str, ...] = ()

    @classmethod
    def _collect(cls, manager: _AddonManager | None = None) -> Version:
        return cls(
            vethuq=_Version.app_version(),
            python=_Version.python_version(),
            platform=_Version.platform_name(),
            db_schema=_Version.db_schema(),
            file_types=_Version.file_types(manager),
            search_engines=_Version.search_engines(manager),
            ocr_engines=_Version.ocr_engines(manager),
            ocr_languages=_Version.ocr_languages(manager),
            add_ons=_Version.add_ons(manager),
            bundles=_Version.bundles(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "vethuq": self.vethuq,
            "python": self.python,
            "platform": self.platform,
            "db_schema": self.db_schema,
            "file_types": list(self.file_types),
            "search_engines": list(self.search_engines),
            "ocr_engines": list(self.ocr_engines),
            "ocr_languages": list(self.ocr_languages),
            "add_ons": list(self.add_ons),
            "bundles": list(self.bundles),
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
