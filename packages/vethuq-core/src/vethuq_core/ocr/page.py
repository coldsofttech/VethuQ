"""Deciding which of a document's read pages need OCR, and running it."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from vethuq_core.ocr.engines import Engines, OcrResult
from vethuq_core.readers import PageResult, Reader, ReadPage


class PageOcr:
    # A page's native text layer counts as usable content once it clears both floors -
    # short enough to reject a stray artifact (e.g. a scanner-stamped filename) that
    # would otherwise mask a page that's actually a scanned image.
    MIN_NATIVE_TEXT_CHARS = 20
    MIN_NATIVE_TEXT_WORDS = 3

    @staticmethod
    def is_native_text(text: str) -> bool:
        stripped = text.strip()
        return (
            len(stripped) >= PageOcr.MIN_NATIVE_TEXT_CHARS
            and len(stripped.split()) >= PageOcr.MIN_NATIVE_TEXT_WORDS
        )

    @staticmethod
    def page_result(result: OcrResult) -> PageResult:
        return PageResult(
            text=result.text,
            confidence=result.confidence,
            source="ocr",
            ocr_engine=result.engine,
            language=result.language,
            image_width=result.image_width,
            image_height=result.image_height,
        )

    @staticmethod
    def ocr_page(conn: sqlite3.Connection, page: ReadPage) -> PageResult:
        """Classify a page as native, scanned, or mixed and extract accordingly.

        Native text is taken directly from the page's text layer with no OCR at all.
        OCR only runs over the page (or, for a mixed page, just the embedded image
        regions) when the native text layer can't account for the page's content.
        """
        native_text = page.native_text
        image_regions = page.image_regions

        if PageOcr.is_native_text(native_text) and not image_regions:
            return PageResult(text=native_text.strip(), confidence=1.0, source="native")

        if PageOcr.is_native_text(native_text) and image_regions:
            engine = Engines.get(conn)
            regions = [engine.recognize(page.render(region)) for region in image_regions]
            combined_text = "\n".join([native_text.strip(), *(region.text for region in regions)])
            combined_confidence = sum(region.confidence for region in regions) / len(regions)
            last = regions[-1]
            return PageResult(
                text=combined_text,
                confidence=combined_confidence,
                source="mixed",
                ocr_engine=last.engine,
                language=last.language,
                image_width=last.image_width,
                image_height=last.image_height,
            )

        return PageOcr.page_result(Engines.get(conn).recognize(page.render(None)))

    @staticmethod
    def ocr_document(conn: sqlite3.Connection, reader: Reader, file_path: Path) -> list[PageResult]:
        return [PageOcr.ocr_page(conn, page) for page in reader.read(file_path)]
