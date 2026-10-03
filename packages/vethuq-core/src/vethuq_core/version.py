"""Version information shown by `vethuq --version`."""

from __future__ import annotations

import platform
from importlib import metadata

from vethuq_core.db.connection import Db


class VersionInfo:
    """Build the label/value rows describing this install: CLI, Python, platform and DB schema."""

    @staticmethod
    def package_version(dist: str) -> str:
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return "unknown"

    @staticmethod
    def rows(dist: str = "vethuq-cli") -> list[tuple[str, str]]:
        return [
            ("VethuQ CLI", VersionInfo.package_version(dist)),
            ("Python", platform.python_version()),
            ("Platform", platform.platform()),
            ("Database schema", str(Db.SCHEMA_VERSION)),
        ]
