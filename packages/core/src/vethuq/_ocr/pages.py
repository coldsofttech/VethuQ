"""Turning a document's pages into text: native first, OCR only where the page needs it."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from vethuq._db.values import _PageSource
from vethuq_addon_api import DocumentReader, OcrEngine, ReadPage


@dataclass(frozen=True)
class _QuickRead:
    """How the quick OCR read of one page went."""

    region_count: int  # the images read on a mixed page; 0 when the whole page was read
    engine: str
    confidence: float
    line_count: int
    char_count: int
    duration_ms: int


@dataclass(frozen=True)
class _PageResult:
    page_number: int
    text: str
    confidence: float
    source: _PageSource
    image_width: int | None = None
    image_height: int | None = None
    quick: _QuickRead | None = None


class _PageOcr:
    """Decides, page by page, whether the text layer is enough.

    - **native**: the text layer has enough text (20 characters, 3 words) and the page has no
      images worth reading: its text is used and no OCR runs.
    - **mixed**: enough text, plus images: only the images are read, and appended.
    - **scanned**: not enough text: the whole page is read.
    """

    MIN_CHARS = 20
    MIN_WORDS = 3

    @staticmethod
    def has_text(text: str) -> bool:
        stripped = text.strip()
        return len(stripped) >= _PageOcr.MIN_CHARS and len(stripped.split()) >= _PageOcr.MIN_WORDS

    @staticmethod
    def needs_ocr(page: ReadPage) -> bool:
        return not _PageOcr.has_text(page.native_text) or bool(page.image_regions)

    @staticmethod
    def pages(reader: DocumentReader, path: Path) -> Iterator[tuple[int, ReadPage]]:
        yield from enumerate(reader.read(path), start=1)

    @staticmethod
    def read_page(
        number: int, page: ReadPage, engine_for: Callable[[], OcrEngine] | None
    ) -> _PageResult:
        """Read one page. `engine_for` gives the OCR engine when one is needed (None: no OCR is
        possible, so a page that needs it raises `LookupError`)."""
        native = page.native_text.strip()
        if not _PageOcr.needs_ocr(page):
            return _PageResult(number, native, 1.0, _PageSource.NATIVE)
        if engine_for is None:
            raise LookupError("OCR isn't available")
        engine = engine_for()
        has_text = _PageOcr.has_text(native)
        regions = list(page.image_regions) if has_text else [None]
        texts: list[str] = []
        confidences: list[float] = []
        lines = 0
        width = height = None
        started = time.perf_counter()
        for region in regions:
            result = engine.recognize(page.render(region))
            if result.text.strip():
                texts.append(result.text.strip())
                confidences.append(result.confidence)
            lines += len(result.lines) or len(result.text.splitlines())
            width, height = result.image_width or width, result.image_height or height
        duration = int((time.perf_counter() - started) * 1000)
        ocr_text = "\n".join(texts)
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        quick = _QuickRead(
            region_count=len(regions) if has_text else 0,
            engine=engine.name,
            confidence=confidence,
            line_count=lines,
            char_count=len(ocr_text),
            duration_ms=duration,
        )
        if has_text:
            text = f"{native}\n{ocr_text}" if ocr_text else native
            return _PageResult(
                number,
                text,
                confidence if ocr_text else 1.0,
                _PageSource.MIXED,
                width,
                height,
                quick,
            )
        # A scanned page: the OCR text, or whatever little native text there was if OCR found none.
        return _PageResult(
            number, ocr_text or native, confidence, _PageSource.OCR, width, height, quick
        )
