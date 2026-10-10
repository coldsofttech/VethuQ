"""Collecting what this install is running: VethuQ, Python, the platform and the schema."""

from __future__ import annotations

import platform
from importlib import metadata

from vethuq._db import _Schema


class _Version:
    DISTRIBUTION = "VethuQ"
    FALLBACK = "0.1.0"  # when running from a source tree that isn't installed

    @staticmethod
    def app_version() -> str:
        """The installed VethuQ version (from the git tags, through hatch-vcs)."""
        try:
            return metadata.version(_Version.DISTRIBUTION)
        except metadata.PackageNotFoundError:
            return _Version.FALLBACK

    @staticmethod
    def python_version() -> str:
        return platform.python_version()

    @staticmethod
    def platform_name() -> str:
        return platform.platform()

    @staticmethod
    def db_schema() -> int:
        """The database schema version this build reads and writes."""
        return _Schema.VERSION

    # Placeholders: these will list what is installed once the catalogs behind them exist.

    @staticmethod
    def file_types() -> tuple[str, ...]:
        return ()

    @staticmethod
    def search_engines() -> tuple[str, ...]:
        return ()

    @staticmethod
    def ocr_engines() -> tuple[str, ...]:
        return ()

    @staticmethod
    def ocr_languages() -> tuple[str, ...]:
        return ()

    @staticmethod
    def add_ons() -> tuple[str, ...]:
        return ()

    @staticmethod
    def bundles() -> tuple[str, ...]:
        return ()
