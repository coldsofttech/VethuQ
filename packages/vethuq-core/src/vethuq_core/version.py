"""Version information shown by `vethuq --version` and `client.version`."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from importlib import metadata

from vethuq_core.db.connection import Db


@dataclass(frozen=True)
class VersionDetails:
    """What this install is running: VethuQ, Python, platform and database schema."""

    vethuq: str
    python: str
    platform: str
    db_schema: int


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
            db_schema=Db.SCHEMA_VERSION,
        )

    @staticmethod
    def rows() -> list[tuple[str, str]]:
        d = VersionInfo.details()
        return [
            ("VethuQ CLI", d.vethuq),
            ("Python", d.python),
            ("Platform", d.platform),
            ("Database schema", str(d.db_schema)),
        ]
