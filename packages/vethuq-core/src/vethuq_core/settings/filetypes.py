"""The file types and search engines installed in this VethuQ, as last recorded in the database."""

from __future__ import annotations

import json

from vethuq_core.filetypes import FileTypes
from vethuq_core.search.engines.catalog import SearchEngineCatalog
from vethuq_core.settings.settings import Settings
from vethuq_core.storage import Storage


class FileTypeSettings:
    INSTALLED_KEY = "installed_file_types"
    INSTALLED_ENGINES_KEY = "installed_search_engines"

    @staticmethod
    def record_installed(storage: Storage) -> list[str]:
        """Store the installed `type-*` extras (e.g. ['type-pdf']) and return them."""
        extras = [t.extra for t in FileTypes.installed()]
        Settings.set(storage, FileTypeSettings.INSTALLED_KEY, json.dumps(extras))
        return extras

    @staticmethod
    def get_installed(storage: Storage) -> list[str]:
        """The `type-*` extras recorded by the last `record_installed` (empty if never)."""
        value = Settings.get(storage, FileTypeSettings.INSTALLED_KEY)
        return list(json.loads(value)) if value else []

    @staticmethod
    def record_installed_engines(storage: Storage) -> list[str]:
        """Store the installed `search-*` extras (e.g. ['search-like']) and return them."""
        extras = [e.extra for e in SearchEngineCatalog.installed()]
        Settings.set(storage, FileTypeSettings.INSTALLED_ENGINES_KEY, json.dumps(extras))
        return extras

    @staticmethod
    def get_installed_engines(storage: Storage) -> list[str]:
        value = Settings.get(storage, FileTypeSettings.INSTALLED_ENGINES_KEY)
        return list(json.loads(value)) if value else []
