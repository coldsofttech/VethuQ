"""Which OCR engines and recognition languages this install has.

Both are described by manifests (`engines/manifests/<id>.json`, `languages/manifests/<id>.json`)
that share the search-engine manifest shape. One is *installed* when its `modules` import and
every package in its `requires` is present.
"""

from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass
from importlib import metadata, resources
from typing import Any


@dataclass(frozen=True)
class OcrComponentInfo:
    id: str
    label: str
    extra: str
    requires: tuple[str, ...]
    modules: tuple[str, ...]
    default: bool

    @staticmethod
    def from_manifest(data: dict[str, Any]) -> OcrComponentInfo:
        return OcrComponentInfo(
            id=data["id"],
            label=data["label"],
            extra=data["extra"],
            requires=tuple(data.get("requires", ())),
            modules=tuple(data.get("modules", ())),
            default=bool(data.get("default", False)),
        )

    def is_installed(self) -> bool:
        try:
            if not all(importlib.util.find_spec(name) is not None for name in self.modules):
                return False
            for requirement in self.requires:
                name = re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0]
                metadata.version(name)
        except (ImportError, ValueError, metadata.PackageNotFoundError):
            return False
        return True


class OcrCatalog:
    _cache: dict[str, tuple[OcrComponentInfo, ...]] = {}

    @staticmethod
    def _load(package: str) -> tuple[OcrComponentInfo, ...]:
        if package not in OcrCatalog._cache:
            folder = resources.files("vethuq_core").joinpath("ocr", package, "manifests")
            found = [
                OcrComponentInfo.from_manifest(json.loads(entry.read_text("utf-8")))
                for entry in folder.iterdir()
                if entry.name.endswith(".json")
            ]
            OcrCatalog._cache[package] = tuple(sorted(found, key=lambda c: (not c.default, c.id)))
        return OcrCatalog._cache[package]

    @staticmethod
    def engines() -> tuple[OcrComponentInfo, ...]:
        """Every OCR engine shipped in this build, default first, then by id."""
        return OcrCatalog._load("engines")

    @staticmethod
    def languages() -> tuple[OcrComponentInfo, ...]:
        """Every OCR language shipped in this build, default first, then by id."""
        return OcrCatalog._load("languages")

    @staticmethod
    def installed_engines() -> list[OcrComponentInfo]:
        return [e for e in OcrCatalog.engines() if e.is_installed()]

    @staticmethod
    def installed_languages() -> list[OcrComponentInfo]:
        return [lang for lang in OcrCatalog.languages() if lang.is_installed()]
