"""The file types installed in this VethuQ, as last recorded in the database."""

from __future__ import annotations

import json

from vethuq_core.filetypes import FileTypes
from vethuq_core.settings.settings import Settings
from vethuq_core.storage import Storage


class FileTypeSettings:
    INSTALLED_KEY = "installed_file_types"

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
