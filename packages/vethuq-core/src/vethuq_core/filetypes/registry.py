"""Discovers file types from their manifests and tracks which are installed and enabled."""

from __future__ import annotations

import json
import logging
from importlib import resources
from pathlib import Path

from vethuq_core.filetypes.filetype import FileType
from vethuq_core.paths import Paths

_logger = logging.getLogger(__name__)


class FileTypes:
    """All file types, by status.

    *Installed* means the type's dependencies import. *Enabled* means installed and, when the
    installer recorded a selection (`SELECTION_FILENAME` in the data root), chosen in it. Only
    enabled types are scanned and indexed.
    """

    MANIFEST_FILENAME = "type.json"
    SELECTION_FILENAME = "file_types.json"
    SELECTION_KEY = "enabled"

    _cache: tuple[FileType, ...] | None = None

    @staticmethod
    def all() -> tuple[FileType, ...]:
        """Every file type shipped in this build, sorted by id."""
        if FileTypes._cache is None:
            found = []
            for entry in resources.files("vethuq_core.filetypes").iterdir():
                manifest = entry.joinpath(FileTypes.MANIFEST_FILENAME)
                if entry.is_dir() and manifest.is_file():
                    found.append(FileType.from_manifest(json.loads(manifest.read_text("utf-8"))))
            FileTypes._cache = tuple(sorted(found, key=lambda t: t.id))
        return FileTypes._cache

    @staticmethod
    def get(type_id: str) -> FileType | None:
        return next((t for t in FileTypes.all() if t.id == type_id), None)

    @staticmethod
    def installed() -> list[FileType]:
        return [t for t in FileTypes.all() if t.is_installed()]

    @staticmethod
    def missing() -> list[FileType]:
        return [t for t in FileTypes.all() if not t.is_installed()]

    @staticmethod
    def selection_file() -> Path:
        return Paths.default_data_root() / FileTypes.SELECTION_FILENAME

    @staticmethod
    def selection() -> set[str] | None:
        """The ids chosen at install time, or None when nothing was recorded (all enabled).

        The installer cannot know a relocated data root, so it records the selection in the
        platform default folder; that is checked too.
        """
        for path in dict.fromkeys(
            (FileTypes.selection_file(), Paths.platform_data_root() / FileTypes.SELECTION_FILENAME)
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return {str(i) for i in data[FileTypes.SELECTION_KEY]}
            except FileNotFoundError:
                continue
            except (OSError, ValueError, KeyError, TypeError):
                _logger.warning("Ignoring unreadable file type selection %s", path)
        return None

    @staticmethod
    def save_selection(type_ids: list[str]) -> None:
        path = FileTypes.selection_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({FileTypes.SELECTION_KEY: sorted(set(type_ids))}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def is_enabled(file_type: FileType) -> bool:
        if not file_type.is_installed():
            return False
        selection = FileTypes.selection()
        return selection is None or file_type.id in selection

    @staticmethod
    def enabled() -> list[FileType]:
        return [t for t in FileTypes.all() if FileTypes.is_enabled(t)]

    @staticmethod
    def for_extension(extension: str) -> FileType | None:
        """The file type that owns `extension` (e.g. ".pdf"), whether or not it is usable."""
        extension = extension.lower()
        return next((t for t in FileTypes.all() if extension in t.extensions), None)

    @staticmethod
    def unavailable_reason(file_type: FileType) -> str | None:
        """Why `file_type` is not scanned or indexed (None when it is enabled)."""
        if not file_type.is_installed():
            return (
                f"{file_type.label} support is not installed. "
                f"Install it with: {file_type.install_hint}"
            )
        if not FileTypes.is_enabled(file_type):
            return (
                f"{file_type.label} support is installed but not enabled. "
                "Re-run the installer to enable it"
            )
        return None
