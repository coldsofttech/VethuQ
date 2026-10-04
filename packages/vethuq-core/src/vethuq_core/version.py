"""Version information shown by `vethuq --version` and `client.version`."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from importlib import metadata

from vethuq_core.filetypes import FileTypes
from vethuq_core.search.engines.catalog import SearchEngineCatalog
from vethuq_core.storage import schema_version


@dataclass(frozen=True)
class VersionDetails:
    """What this install is running: VethuQ, Python, platform and database schema."""

    vethuq: str
    python: str
    platform: str
    db_schema: int
    file_types: tuple[str, ...] = ()
    search_engines: tuple[str, ...] = ()


class VersionInfo:
    # Published as `vethuq` (CLI + library merged); `vethuq-cli` in the dev workspace.
    DISTRIBUTIONS = ("vethuq", "vethuq-cli")

    @staticmethod
    def vethuq_version() -> str:
        for dist in VersionInfo.DISTRIBUTIONS:
            try:
                return metadata.version(dist)
            except metadata.PackageNotFoundError:
                continue
        return "unknown"

    @staticmethod
    def details() -> VersionDetails:
        return VersionDetails(
            vethuq=VersionInfo.vethuq_version(),
            python=platform.python_version(),
            platform=platform.platform(),
            db_schema=schema_version(),
            file_types=tuple(t.extra for t in FileTypes.installed()),
            search_engines=tuple(e.extra for e in SearchEngineCatalog.installed()),
        )

    @staticmethod
    def rows() -> list[tuple[str, str]]:
        d = VersionInfo.details()
        return [
            ("VethuQ CLI", d.vethuq),
            ("Python", d.python),
            ("Platform", d.platform),
            ("Database schema", str(d.db_schema)),
            ("File types", ", ".join(d.file_types) or "none"),
            ("Search engines", ", ".join(d.search_engines) or "none"),
        ]
