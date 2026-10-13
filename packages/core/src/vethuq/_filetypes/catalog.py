"""Which kinds of file VethuQ can read: the file types its add-ons provide."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vethuq_addon_api import DocumentReader, FileTypeSpec


class _FileTypeCatalog:
    """Where the file types come from: a function returning the specs of the loaded add-ons."""

    def __init__(
        self,
        specs: Callable[[], list[FileTypeSpec]],
        disabled: Callable[[], set[str]] | None = None,
    ) -> None:
        """`disabled` returns the ids the user switched off; without it every type is on."""
        self.specs = specs
        self._disabled = disabled

    def disabled_ids(self) -> set[str]:
        return self._disabled() if self._disabled is not None else set()

    @staticmethod
    def extension(path: str | Path) -> str:
        return Path(path).suffix.lower()

    def for_path(self, path: str | Path, include_disabled: bool = False) -> FileTypeSpec | None:
        """The available, enabled file type that reads `path`, or None (not supported, its
        add-on isn't installed or can't be used now, or it is switched off). With
        `include_disabled` a switched-off type is still named: for telling what a file is,
        rather than for reading it."""
        extension = self.extension(path)
        candidates = [s for s in self.specs() if s.available and extension in s.extensions]
        if not candidates:
            return None
        if include_disabled:
            return candidates[0]
        disabled = self.disabled_ids()
        return next((s for s in candidates if s.id not in disabled), None)

    def reader_for(self, path: str | Path) -> DocumentReader | None:
        """The reader of the available file type that reads `path`, or None."""
        spec = self.for_path(path)
        return spec.reader if spec is not None else None

    def is_supported(self, path: str | Path) -> bool:
        return self.for_path(path) is not None
