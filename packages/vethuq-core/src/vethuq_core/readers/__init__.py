"""Document readers: extract a file's pages (native text, image regions, lazy render)."""

from __future__ import annotations

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
    "ImagePageStorage",
    "ImageReader",
    "JpgReader",
    "PageResult",
    "PageStorage",
    "PdfPageStorage",
    "PdfReader",
    "PngReader",
    "ReadPage",
    "Reader",
    "Readers",
    "Region",
]
