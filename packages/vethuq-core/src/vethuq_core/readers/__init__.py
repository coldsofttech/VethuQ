"""Document readers: extract a file's pages (native text, image regions, lazy render)."""

from __future__ import annotations

from vethuq_core.readers.errors import (
    CorruptedFileError,
    FileRemovedError,
    OutsideSourceError,
    PasswordProtectedError,
    UnreadableFileError,
)
from vethuq_core.readers.reader import (
    DocumentReader,
    ImageReader,
    ReadPage,
    Region,
)
from vethuq_core.readers.registry import Readers
from vethuq_core.readers.storage import (
    ImagePageStorage,
    PageResult,
    PageStorage,
    PdfPageStorage,
)

__all__ = [
    "CorruptedFileError",
    "FileRemovedError",
    "OutsideSourceError",
    "ImagePageStorage",
    "ImageReader",
    "PageResult",
    "PageStorage",
    "PasswordProtectedError",
    "PdfPageStorage",
    "ReadPage",
    "DocumentReader",
    "Readers",
    "Region",
    "UnreadableFileError",
]
