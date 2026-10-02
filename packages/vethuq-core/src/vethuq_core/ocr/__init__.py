"""OCR indexing pipeline: turns registered sources into searchable text."""

from __future__ import annotations

from vethuq_core.ocr.deepening import Deepening, DeepenUnit
from vethuq_core.ocr.document import Document, DocumentResult
from vethuq_core.ocr.engine import Engine
from vethuq_core.ocr.metrics import Metrics
from vethuq_core.ocr.pending import Pending, PendingFile
from vethuq_core.ocr.quick import Quick
from vethuq_core.ocr.reader import (
    DocReader,
    DocxReader,
    ImageReader,
    JpgReader,
    PageResult,
    PdfReader,
    PngReader,
    PptReader,
    PptxReader,
    Reader,
    Readers,
    XlsReader,
    XlsxReader,
)
from vethuq_core.ocr.runner import Ocr
from vethuq_core.ocr.scheduler import Scheduler

__all__ = [
    "Deepening",
    "DeepenUnit",
    "Document",
    "DocReader",
    "DocumentResult",
    "DocxReader",
    "Engine",
    "ImageReader",
    "JpgReader",
    "Metrics",
    "Ocr",
    "PageResult",
    "PdfReader",
    "Pending",
    "PendingFile",
    "PngReader",
    "PptReader",
    "PptxReader",
    "Quick",
    "Reader",
    "Readers",
    "Scheduler",
    "XlsReader",
    "XlsxReader",
]
