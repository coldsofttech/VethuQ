"""The registered readers, by file extension."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from vethuq_core.readers.reader import JpgReader, PdfReader, PngReader, Reader


class Readers:
    """Looks readers up by file path or file type. Supporting a new file format is a
    `Reader` subclass plus `Readers.register` - the OCR pipeline only ever sees the
    `Reader` abstraction, keyed off `file_type`."""

    _BY_SUFFIX: dict[str, Reader] = {}

    @staticmethod
    def register(extensions: str | tuple[str, ...], reader: Reader) -> None:
        """Handle files with the given extension(s) (e.g. `".tiff"`) using `reader`."""
        for extension in (extensions,) if isinstance(extensions, str) else extensions:
            Readers._BY_SUFFIX[extension.lower()] = reader

    @staticmethod
    def for_path(file_path: Path) -> Reader:
        """The reader registered for `file_path`'s extension (KeyError if none)."""
        return Readers._BY_SUFFIX[file_path.suffix.lower()]

    @staticmethod
    def for_file_type(file_type: str) -> Reader:
        """A reader that handles `file_type` (KeyError if none does).

        Readers sharing a `file_type` share its storage and weight, so any one of
        them stands in for the type as a whole.
        """
        for reader in Readers._BY_SUFFIX.values():
            if reader.file_type == file_type:
                return reader
        raise KeyError(file_type)

    @staticmethod
    def is_supported(file_path: Path) -> bool:
        return file_path.suffix.lower() in Readers._BY_SUFFIX

    @staticmethod
    def iter_files(path: Path) -> Iterator[Path]:
        """Yield `path` (if it's a supported file) or every supported file beneath it."""
        if path.is_file():
            if Readers.is_supported(path):
                yield path
            return
        for candidate in path.rglob("*"):
            if candidate.is_file() and Readers.is_supported(candidate):
                yield candidate

    @staticmethod
    def new_file_type_counts() -> dict[str, int]:
        """A zeroed `{file_type: count}` for every file type registered readers handle."""
        return dict.fromkeys((reader.file_type for reader in Readers._BY_SUFFIX.values()), 0)

    @staticmethod
    def file_type_weight(file_type: str) -> float:
        """The `processing_weight` of `file_type`'s readers (1.0 for an unregistered type)."""
        try:
            return Readers.for_file_type(file_type).processing_weight
        except KeyError:
            return 1.0


Readers.register(".pdf", PdfReader())
Readers.register(".png", PngReader())
Readers.register((".jpg", ".jpeg"), JpgReader())
