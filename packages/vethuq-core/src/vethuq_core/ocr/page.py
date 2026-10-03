"""Deciding which of a document's read pages need OCR, and running it."""

from __future__ import annotations

from pathlib import Path

from vethuq_core.logs import Logs
from vethuq_core.ocr.engines import Engines, OcrResult
from vethuq_core.readers import PageResult, Reader, ReadPage, UnreadableFileError
from vethuq_core.storage import Storage

_logger = Logs.get_logger("index")


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
    def ocr_page(storage: Storage, page: ReadPage) -> PageResult:
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
            engine = Engines.get(storage)
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

        return PageOcr.page_result(Engines.get(storage).recognize(page.render(None)))

    @staticmethod
    def ocr_document(storage: Storage, reader: Reader, file_path: Path) -> list[PageResult]:
        """Extract every page of `file_path`, logging what failed and where.

        A failure while the reader produces a page (opening the file, its native
        text layer, rendering) is logged as an extraction failure; one inside
        `ocr_page` (the OCR engine) as an OCR failure, with the page and engine.
        Both are re-raised unchanged for the retry/error handling above.
        """
        results: list[PageResult] = []
        pages = iter(reader.read(file_path))
        page_number = 0
        while True:
            try:
                page = next(pages)
            except StopIteration:
                return results
            except Exception as exc:
                _logger.error(
                    "Extraction failed: file=%s page=%d reader=%s error=%s: %s",
                    file_path,
                    page_number + 1,
                    type(reader).__name__,
                    type(exc).__name__,
                    exc,
                    exc_info=not isinstance(exc, UnreadableFileError),
                )
                raise
            page_number += 1
            try:
                results.append(PageOcr.ocr_page(storage, page))
            except Exception as exc:
                _logger.error(
                    "OCR failed: file=%s page=%d engine=%s error=%s: %s",
                    file_path,
                    page_number,
                    PageOcr.engine_name(storage),
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                raise

    @staticmethod
    def engine_name(storage: Storage) -> str:
        """The calling thread's OCR engine label for log lines - never raises."""
        try:
            return Engines.get(storage).name
        except Exception:  # noqa: BLE001 - only used to enrich a log line
            return "unknown"
