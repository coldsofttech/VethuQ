"""The registered readers, by file extension."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from vethuq_core.fspath import FsPath
from vethuq_core.readers.reader import DocumentReader, JpgReader, PdfReader, PngReader


class Readers:
    """Looks readers up by file path or file type. Supporting a new file format is a
    `DocumentReader` subclass plus `Readers.register` - the OCR pipeline only ever sees the
    `DocumentReader` abstraction, keyed off `file_type`."""

    _BY_SUFFIX: dict[str, DocumentReader] = {}

    # `document_index.file_type` of a file no reader handles.
    UNSUPPORTED_FILE_TYPE = "unsupported"

    # OS bookkeeping files that aren't really the user's documents.
    _JUNK_FILE_NAMES = frozenset({"thumbs.db", "ehthumbs.db", "desktop.ini"})
    _WINDOWS_HIDDEN_ATTRIBUTE = 0x2

    @staticmethod
    def register(extensions: str | tuple[str, ...], reader: DocumentReader) -> None:
        """Handle files with the given extension(s) (e.g. `".tiff"`) using `reader`."""
        for extension in (extensions,) if isinstance(extensions, str) else extensions:
            Readers._BY_SUFFIX[extension.lower()] = reader

    @staticmethod
    def for_path(file_path: Path) -> DocumentReader:
        """The reader registered for `file_path`'s extension (KeyError if none)."""
        return Readers._BY_SUFFIX[file_path.suffix.lower()]

    @staticmethod
    def for_file_type(file_type: str) -> DocumentReader:
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
        if FsPath.extended(path).is_file():
            if Readers.is_supported(path):
                yield path
            return
        for candidate in Readers._walk(path):
            if Readers.is_supported(candidate):
                yield candidate

    @staticmethod
    def _walk(root: Path) -> Iterator[Path]:
        """Every file beneath `root` as a normal (not extended-length) path, long ones included."""
        extended_root = FsPath.extended(root)
        for dir_path, _, names in os.walk(extended_root):
            folder = root / Path(dir_path).relative_to(extended_root)
            for name in names:
                candidate = folder / name
                if FsPath.extended(candidate).is_file():
                    yield candidate

    @staticmethod
    def is_hidden(file_path: Path, root: Path) -> bool:
        """Whether `file_path` is a hidden/system file (or sits in a hidden folder under `root`)."""
        try:
            relative_parts = file_path.relative_to(root).parts or (file_path.name,)
        except ValueError:
            relative_parts = (file_path.name,)
        if any(part.startswith(".") for part in relative_parts):
            return True
        if file_path.name.lower() in Readers._JUNK_FILE_NAMES:
            return True
        attributes = getattr(FsPath.extended(file_path).stat(), "st_file_attributes", 0)
        return bool(attributes & Readers._WINDOWS_HIDDEN_ATTRIBUTE)

    @staticmethod
    def iter_unsupported_files(path: Path) -> Iterator[Path]:
        """Yield `path` (if it's an unsupported, non-hidden file) or every such file beneath it."""
        if FsPath.extended(path).is_file():
            if not Readers.is_supported(path) and not Readers.is_hidden(path, path.parent):
                yield path
            return
        for candidate in Readers._walk(path):
            if not Readers.is_supported(candidate) and not Readers.is_hidden(candidate, path):
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
