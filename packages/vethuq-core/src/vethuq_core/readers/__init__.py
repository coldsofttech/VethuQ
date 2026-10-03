"""Document readers: extract a file's pages (native text, image regions, lazy render)."""

from __future__ import annotations

from vethuq_core.readers.errors import (
    CorruptedFileError,
    FileRemovedError,
    PasswordProtectedError,
    UnreadableFileError,
)
from vethuq_core.readers.reader import (
    ImageReader,
    JpgReader,
    PdfReader,
    PngReader,
    Reader,
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
    "ImagePageStorage",
    "ImageReader",
    "JpgReader",
    "PageResult",
    "PageStorage",
    "PasswordProtectedError",
    "PdfPageStorage",
    "PdfReader",
    "PngReader",
    "ReadPage",
    "Reader",
    "Readers",
    "Region",
    "UnreadableFileError",
]
