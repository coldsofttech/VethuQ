"""Which search engines this install has: manifests, and the installer's selection.

Mirrors `vethuq_core.filetypes`: every engine has a manifest in `manifests/<id>.json` that is
the single source for its `search-<id>` pip extra and the installer catalog. An engine is
*installed* when its dependencies import (none of today's need any beyond the base install, so
that is always true) and *enabled* when it is also in the selection the installer recorded in
`search_engines.json` (no file means all are enabled). The default engine, `like`, is always
enabled.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from vethuq_core.paths import Paths

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchEngineInfo:
    id: str
    label: str
    extra: str
    requires: tuple[str, ...]
    modules: tuple[str, ...]
    default: bool

    @staticmethod
    def from_manifest(data: dict[str, Any]) -> SearchEngineInfo:
        return SearchEngineInfo(
            id=data["id"],
            label=data["label"],
            extra=data["extra"],
            requires=tuple(data.get("requires", ())),
            modules=tuple(data.get("modules", ())),
            default=bool(data.get("default", False)),
        )

    @property
    def install_hint(self) -> str:
        return f"pip install vethuq[{self.extra}]"

    def is_installed(self) -> bool:
        try:
            return all(importlib.util.find_spec(name) is not None for name in self.modules)
        except (ImportError, ValueError):
            return False


class SearchEngineCatalog:
    SELECTION_FILENAME = "search_engines.json"
    SELECTION_KEY = "enabled"

    _cache: tuple[SearchEngineInfo, ...] | None = None

    @staticmethod
    def all() -> tuple[SearchEngineInfo, ...]:
        """Every search engine shipped in this build, default first, then by id."""
        if SearchEngineCatalog._cache is None:
            folder = resources.files("vethuq_core.search.engines").joinpath("manifests")
            found = [
                SearchEngineInfo.from_manifest(json.loads(entry.read_text("utf-8")))
                for entry in folder.iterdir()
                if entry.name.endswith(".json")
            ]
            SearchEngineCatalog._cache = tuple(sorted(found, key=lambda e: (not e.default, e.id)))
        return SearchEngineCatalog._cache

    @staticmethod
    def get(engine_id: str) -> SearchEngineInfo | None:
        return next((e for e in SearchEngineCatalog.all() if e.id == engine_id), None)

    @staticmethod
    def installed() -> list[SearchEngineInfo]:
        return [e for e in SearchEngineCatalog.all() if e.is_installed()]

    @staticmethod
    def selection_file() -> Path:
        return Paths.default_data_root() / SearchEngineCatalog.SELECTION_FILENAME

    @staticmethod
    def selection() -> set[str] | None:
        """The ids chosen at install time, or None when nothing was recorded (all enabled)."""
        for path in dict.fromkeys(
            (
                SearchEngineCatalog.selection_file(),
                Paths.platform_data_root() / SearchEngineCatalog.SELECTION_FILENAME,
            )
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return {str(i) for i in data[SearchEngineCatalog.SELECTION_KEY]}
            except FileNotFoundError:
                continue
            except (OSError, ValueError, KeyError, TypeError):
                _logger.warning("Ignoring unreadable search engine selection %s", path)
        return None

    @staticmethod
    def is_enabled(engine: SearchEngineInfo) -> bool:
        if not engine.is_installed():
            return False
        selection = SearchEngineCatalog.selection()
        return engine.default or selection is None or engine.id in selection

    @staticmethod
    def enabled() -> list[SearchEngineInfo]:
        return [e for e in SearchEngineCatalog.all() if SearchEngineCatalog.is_enabled(e)]

    @staticmethod
    def is_name_enabled(name: str) -> bool:
        """Whether engine `name` can be used; names this catalog doesn't know count as enabled."""
        engine = SearchEngineCatalog.get(name)
        return engine is None or SearchEngineCatalog.is_enabled(engine)

    @staticmethod
    def unavailable_reason(engine: SearchEngineInfo) -> str | None:
        """Why `engine` can't be used (None when it is enabled)."""
        if not engine.is_installed():
            return (
                f"The {engine.id} search engine is not installed. "
                f"Install it with: {engine.install_hint}"
            )
        if not SearchEngineCatalog.is_enabled(engine):
            return (
                f"The {engine.id} search engine is installed but not enabled. "
                "Re-run the installer to enable it"
            )
        return None
