"""Collecting what this install is running: VethuQ, Python, the platform and the schema."""

from __future__ import annotations

import platform
from importlib import metadata
from typing import TYPE_CHECKING

from vethuq._db import _Schema

if TYPE_CHECKING:
    from vethuq._addons import _AddonManager


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

    # What is installed comes from the add-ons that are running: each kind lists the ids the
    # add-on manager found (so an add-on that failed to load or is turned off adds nothing). With
    # no manager, which is a bare `_Version` outside a client, every list is empty.

    @staticmethod
    def file_types(manager: _AddonManager | None = None) -> tuple[str, ...]:
        return _Version._ids(manager, "file_type_specs")

    @staticmethod
    def search_engines(manager: _AddonManager | None = None) -> tuple[str, ...]:
        return _Version._ids(manager, "search_engine_specs")

    @staticmethod
    def ocr_engines(manager: _AddonManager | None = None) -> tuple[str, ...]:
        return _Version._ids(manager, "ocr_engine_providers")

    @staticmethod
    def ocr_languages(manager: _AddonManager | None = None) -> tuple[str, ...]:
        return _Version._ids(manager, "language_specs")

    @staticmethod
    def add_ons(manager: _AddonManager | None = None) -> tuple[str, ...]:
        """The add-ons that are running, by id."""
        if manager is None:
            return ()
        running = (item.id for item in manager.loaded().values() if item.addon is not None)
        return tuple(sorted(running))

    @staticmethod
    def _ids(manager: _AddonManager | None, method: str) -> tuple[str, ...]:
        if manager is None:
            return ()
        return tuple(sorted({spec.id for spec in getattr(manager, method)()}))
    
    BUNDLE_GROUP = "vethuq.bundles"

    @staticmethod
    def bundles() -> tuple[str, ...]:
        """The bundles installed (`vethuq-bundle-<name>`), by name: each registers itself under
        the `vethuq.bundles` entry point group."""
        return tuple(sorted({e.name for e in metadata.entry_points(group=_Version.BUNDLE_GROUP)}))
