"""The registered readers, by file extension."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from vethuq_core.filetypes import FileType, FileTypes
from vethuq_core.paths.fspath import FsPath
from vethuq_core.readers.reader import DocumentReader


class Readers:
    """Looks readers up by file path or file type. Supporting a new file format is a
    `DocumentReader` subclass plus `Readers.register` - the OCR pipeline only ever sees the
    `DocumentReader` abstraction, keyed off `file_type`."""

    _BY_SUFFIX: dict[str, DocumentReader] = {}
    # The enabled file types' readers register on first use, not at import: a reader module
    # imports `vethuq_core.readers`, so registering while this module loads would be circular.
    _loaded = False

    # `document_index.file_type` of a file no reader handles.
    UNSUPPORTED_FILE_TYPE = "unsupported"

    # OS bookkeeping files that aren't really the user's documents.
    _JUNK_FILE_NAMES = frozenset({"thumbs.db", "ehthumbs.db", "desktop.ini"})
    _WINDOWS_HIDDEN_ATTRIBUTE = 0x2

    @staticmethod
    def _readers() -> dict[str, DocumentReader]:
        if not Readers._loaded:
            Readers._loaded = True
            for file_type in FileTypes.enabled():
                for extension in file_type.extensions:
                    Readers._BY_SUFFIX.setdefault(extension, file_type.load_reader())
        return Readers._BY_SUFFIX

    @staticmethod
    def register(extensions: str | tuple[str, ...], reader: DocumentReader) -> None:
        """Handle files with the given extension(s) (e.g. `".tiff"`) using `reader`."""
        readers = Readers._readers()
        for extension in (extensions,) if isinstance(extensions, str) else extensions:
            readers[extension.lower()] = reader

    @staticmethod
    def for_path(file_path: Path) -> DocumentReader:
        """The reader registered for `file_path`'s extension (KeyError if none)."""
        return Readers._readers()[file_path.suffix.lower()]

    @staticmethod
    def for_file_type(file_type: str) -> DocumentReader:
        """A reader that handles `file_type` (KeyError if none does).

        Readers sharing a `file_type` share its storage and weight, so any one of
        them stands in for the type as a whole.
        """
        for reader in Readers._readers().values():
            if reader.file_type == file_type:
                return reader
        raise KeyError(file_type)

    @staticmethod
    def is_supported(file_path: Path) -> bool:
        return file_path.suffix.lower() in Readers._readers()

    @staticmethod
    def unavailable_type(file_path: Path) -> FileType | None:
        """The known file type `file_path` belongs to when it is not installed or enabled."""
        file_type = FileTypes.for_extension(file_path.suffix)
        if file_type is None or Readers.is_supported(file_path):
            return None
        return file_type

    @staticmethod
    def unsupported_reason(file_path: Path) -> str:
        """Why `file_path` is not indexed, for its 'unsupported' `document_index` row."""
        file_type = Readers.unavailable_type(file_path)
        reason = FileTypes.unavailable_reason(file_type) if file_type is not None else None
        return reason or f"Unsupported file format: {file_path.suffix or file_path.name}"

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
        return dict.fromkeys((reader.file_type for reader in Readers._readers().values()), 0)

    @staticmethod
    def file_type_weight(file_type: str) -> float:
        """The `processing_weight` of `file_type`'s readers (1.0 for an unregistered type)."""
        try:
            return Readers.for_file_type(file_type).processing_weight
        except KeyError:
            return 1.0
