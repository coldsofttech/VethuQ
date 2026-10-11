"""Which kinds of file VethuQ can read: the file types its add-ons provide."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vethuq_addon_api import DocumentReader, FileTypeSpec


class _FileTypeCatalog:
    """Where the file types come from: a function returning the specs of the loaded add-ons."""

    def __init__(self, specs: Callable[[], list[FileTypeSpec]]) -> None:
        self.specs = specs

    @staticmethod
    def extension(path: str | Path) -> str:
        return Path(path).suffix.lower()

    def for_path(self, path: str | Path) -> FileTypeSpec | None:
        """The available file type that reads `path`, or None (not supported, or its add-on
        isn't installed or can't be used now)."""
        extension = self.extension(path)
        return next(
            (s for s in self.specs() if s.available and extension in s.extensions),
            None,
        )

    def reader_for(self, path: str | Path) -> DocumentReader | None:
        """The reader of the available file type that reads `path`, or None."""
        spec = self.for_path(path)
        return spec.reader if spec is not None else None

    def is_supported(self, path: str | Path) -> bool:
        return self.for_path(path) is not None
