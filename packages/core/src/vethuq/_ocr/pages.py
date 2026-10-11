"""Turning a document's pages into text: native first, OCR only where the page needs it."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from vethuq._credits import _PageMeter
from vethuq._db.values import _PageSource
from vethuq_addon_api import (
    DocumentReader,
    LanguageSpec,
    OcrExecutor,
    OcrRequest,
    OcrResult,
    ReadPage,
)


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
    credits_milli: int = 0
    size_factor: float = 1.0
    # A page whose OCR is away: nothing is read yet; `requests` are the images to send.
    pending: bool = False
    requests: tuple[OcrRequest, ...] = ()
    ledger_ids: tuple[int, ...] = ()


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
    def covered(page: ReadPage) -> float:
        """The share of the page its image regions cover (1 when the size isn't known)."""
        if not page.width_pt or not page.height_pt:
            return 1.0
        area = sum(max(x1 - x0, 0) * max(y1 - y0, 0) for x0, y0, x1, y1 in page.image_regions)
        return min(area / (page.width_pt * page.height_pt), 1.0)

    @staticmethod
    def combine(
        number: int,
        native: str,
        has_text: bool,
        results: list[OcrResult],
        duration_ms: int,
        factor: float,
        charged: int,
    ) -> _PageResult:
        """A page's text from what OCR read in its images (one for a scanned page, one per image
        on a mixed page) and the page's own text."""
        texts = [r.text.strip() for r in results if r.text.strip()]
        confidences = [r.confidence for r in results if r.text.strip()]
        ocr_text = "\n".join(texts)
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        width = next((r.image_width for r in reversed(results) if r.image_width), None)
        height = next((r.image_height for r in reversed(results) if r.image_height), None)
        lines = sum(len(r.lines) or len(r.text.splitlines()) for r in results)
        engine = next((r.engine for r in reversed(results) if r.engine), "")
        quick = _QuickRead(
            region_count=len(results) if has_text else 0,
            engine=engine,
            confidence=confidence,
            line_count=lines,
            char_count=len(ocr_text),
            duration_ms=duration_ms,
        )
        if has_text:
            text = f"{native}\n{ocr_text}" if ocr_text else native
            return _PageResult(
                number, text, confidence if ocr_text else 1.0, _PageSource.MIXED,
                width, height, quick, charged, factor,
            )  # fmt: skip
        # A scanned page: the OCR text, or whatever little native text there was if OCR found none.
        return _PageResult(
            number, ocr_text or native, confidence, _PageSource.OCR, width, height, quick,
            charged, factor,
        )  # fmt: skip

    @staticmethod
    def read_page(
        number: int,
        page: ReadPage,
        executor: OcrExecutor | None,
        language: LanguageSpec | None = None,
        meter: _PageMeter | None = None,
        key_prefix: str = "",
    ) -> _PageResult:
        """Read one page. `executor` reads the images that need OCR (None: no OCR is possible, so
        a page that needs it raises `LookupError`) in `language`. With a `meter`, the page is
        paid for before it is read; a page that can't be paid for raises
        `CreditsExhaustedError`.

        With an asynchronous executor nothing is read here: the page is paid for, and comes back
        `pending` with the images to send (`requests`, keyed `key_prefix` + page + image index)."""
        native = page.native_text.strip()
        if not _PageOcr.needs_ocr(page):
            return _PageResult(number, native, 1.0, _PageSource.NATIVE)
        if executor is None or language is None:
            raise LookupError("OCR isn't available")
        has_text = _PageOcr.has_text(native)
        regions = list(page.image_regions) if has_text else [None]
        factor, cost, held = 1.0, 0, 0
        if meter is not None:
            factor, cost = meter.quote(
                page.width_pt, page.height_pt, _PageOcr.covered(page) if has_text else 1.0
            )
            held = meter.reserve(cost)
        source = _PageSource.MIXED if has_text else _PageSource.OCR
        try:
            if executor.asynchronous:
                requests = tuple(
                    OcrRequest(
                        key=f"{key_prefix}{number}:{index}",
                        image=page.render(region),
                        language=language,
                        phase="quick",
                        size_factor=factor,
                    )
                    for index, region in enumerate(regions)
                )
                before = len(meter.ledger_ids) if meter is not None else 0
                charged = meter.commit(held, cost, number, factor, "quick") if meter else 0
                paid = tuple(meter.ledger_ids[before:]) if meter is not None else ()
                return _PageResult(
                    number, native, 0.0, source, None, None, None, charged, factor,
                    pending=True, requests=requests, ledger_ids=paid,
                )  # fmt: skip
            results: list[OcrResult] = []
            started = time.perf_counter()
            for index, region in enumerate(regions):
                results.append(
                    executor.recognize(
                        OcrRequest(
                            key=f"{key_prefix}{number}:{index}",
                            image=page.render(region),
                            language=language,
                            phase="quick",
                            size_factor=factor,
                        )
                    )
                )
            duration = int((time.perf_counter() - started) * 1000)
        except BaseException:
            if meter is not None:
                meter.release(held)
            raise
        found = any(r.text.strip() for r in results)
        charged = 0
        if meter is not None:
            actual = cost if found else meter.pricing().blank_milli(cost)
            charged = meter.commit(held, actual, number, factor, "quick")
        return _PageOcr.combine(number, native, has_text, results, duration, factor, charged)
