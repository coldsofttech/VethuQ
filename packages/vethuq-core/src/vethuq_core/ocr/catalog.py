"""Which OCR engines and recognition languages this install has.

Both are described by manifests (`engines/manifests/<id>.json`, `languages/manifests/<id>.json`)
that share the search-engine manifest shape. One is *installed* when its `modules` import and
every package in its `requires` is present.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path
from typing import Any

from vethuq_core.paths import Paths

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrComponentInfo:
    id: str
    label: str
    extra: str
    requires: tuple[str, ...]
    modules: tuple[str, ...]
    default: bool
    # Languages only: the writing system (a key of `vethuq_core.languages.Scripts`) and the
    # language code the OCR engine's models are loaded by. Empty for engines.
    script: str = ""
    paddle_lang: str = ""
    # The language's name in its own script, for the UI and CLI (not the installer, whose
    # script files are not Unicode-safe); empty when it has none worth showing.
    native_label: str = ""

    @staticmethod
    def from_manifest(data: dict[str, Any]) -> OcrComponentInfo:
        return OcrComponentInfo(
            id=data["id"],
            label=data["label"],
            extra=data["extra"],
            requires=tuple(data.get("requires", ())),
            modules=tuple(data.get("modules", ())),
            default=bool(data.get("default", False)),
            script=str(data.get("script", "")),
            paddle_lang=str(data.get("paddle_lang", "")),
            native_label=str(data.get("native_label", "")),
        )

    @property
    def display_label(self) -> str:
        """`Telugu (తెలుగు)`: the label with the native name beside it when there is one."""
        return f"{self.label} ({self.native_label})" if self.native_label else self.label

    @property
    def install_hint(self) -> str:
        return f"pip install vethuq[{self.extra}]"

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
    LANGUAGE_SELECTION_FILENAME = "languages.json"

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

    @staticmethod
    def default_language() -> OcrComponentInfo:
        """The language every install has (English)."""
        return OcrCatalog.languages()[0]

    @staticmethod
    def language(language_id: str) -> OcrComponentInfo | None:
        return next((lang for lang in OcrCatalog.languages() if lang.id == language_id), None)

    @staticmethod
    def language_selection_file() -> Path:
        return Paths.default_data_root() / OcrCatalog.LANGUAGE_SELECTION_FILENAME

    @staticmethod
    def language_selection() -> set[str] | None:
        """The language ids chosen at install time, or None when nothing was recorded (every
        installed language is enabled).

        The installer writes `{"enabled": ["en", "te"]}`; an older one wrote the single choice as
        `{"language": "en"}`, which still reads as that one language.
        """
        for path in dict.fromkeys(
            (
                OcrCatalog.language_selection_file(),
                Paths.platform_data_root() / OcrCatalog.LANGUAGE_SELECTION_FILENAME,
            )
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if "enabled" in data:
                    return {str(i) for i in data["enabled"]}
                return {str(data["language"])}
            except FileNotFoundError:
                continue
            except (OSError, ValueError, KeyError, TypeError):
                _logger.warning("Ignoring unreadable language selection %s", path)
        return None

    @staticmethod
    def is_language_enabled(language: OcrComponentInfo) -> bool:
        """Installed and, when the installer recorded a selection, part of it. English always is."""
        if not language.is_installed():
            return False
        selection = OcrCatalog.language_selection()
        return language.default or selection is None or language.id in selection

    @staticmethod
    def enabled_languages() -> list[OcrComponentInfo]:
        """The languages OCR can use, default first."""
        return [lang for lang in OcrCatalog.languages() if OcrCatalog.is_language_enabled(lang)]
