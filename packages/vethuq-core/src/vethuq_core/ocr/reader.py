"""Readers that turn a file into its OCR'd pages."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    import pymupdf

from vethuq_core.ocr.engine import Engine

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageResult:
    text: str
    confidence: float
    source: str  # 'native' | 'ocr' | 'mixed'
    ocr_engine: str | None = None
    language: str | None = None
    image_width: int | None = None
    image_height: int | None = None

    def phase_columns(self) -> tuple[int, str]:
        """`(ocr_phase, ocr_angles)` to store for a page just read at 0 degrees.

        A native-text page is read straight from the PDF's text layer, not by an
        angle pass - so it's at phase 1 (quick) like any other page, with no angles
        recorded. Deeper phases skip it by its `source`, not by its phase number.
        """
        if self.source == "native":
            return 1, ""
        return 1, "0"


class Reader:
    """Reads one file type into its pages. Extend this to support a new file type.

    `file_type` is the label stored in `document_index`/`processing_metrics`/
    `confidence_metrics` for files this reader handles - most callers branch
    on it rather than on the reader itself, so readers that should share
    existing branches (e.g. all image formats today) must share a `file_type`.
    Persisting a new `file_type`'s pages still needs its own storage (see
    `Quick.process_file`/`Quick.run`) since `pdf_pages`/`image_pages` aren't generic.
    """

    file_type: str

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        raise NotImplementedError


class ImageReader(Reader):
    file_type = "image"

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return [ImageReader.ocr_file(conn, file_path)]

    @staticmethod
    def ocr_array(
        conn: sqlite3.Connection, image: str | np.ndarray
    ) -> tuple[str, float, int | None, int | None]:
        import cv2

        engine = Engine.get(conn)
        result = engine.predict(image)
        page = result[0] if result else {}
        texts = page.get("rec_texts", [])
        scores = page.get("rec_scores", [])
        confidence = sum(scores) / len(scores) if scores else 0.0

        array = cv2.imread(image) if isinstance(image, str) else image
        if array is None:
            return "\n".join(texts), confidence, None, None
        height, width = array.shape[:2]
        return "\n".join(texts), confidence, width, height

    @staticmethod
    def ocr_file(conn: sqlite3.Connection, file_path: Path) -> PageResult:
        text, confidence, width, height = ImageReader.ocr_array(conn, str(file_path))
        return PageResult(
            text=text,
            confidence=confidence,
            source="ocr",
            ocr_engine=Engine.name(),
            language=Engine.LANGUAGE,
            image_width=width,
            image_height=height,
        )


class PdfReader(Reader):
    file_type = "pdf"

    # A page's native text layer counts as usable content once it clears both floors -
    # short enough to reject a stray artifact (e.g. a scanner-stamped filename) that
    # would otherwise mask a page that's actually a scanned image.
    MIN_NATIVE_TEXT_CHARS = 20
    MIN_NATIVE_TEXT_WORDS = 3

    # An embedded image block only forces an OCR pass over its region once it covers
    # a non-trivial share of the page - small logos/rules shouldn't trigger it.
    MIN_IMAGE_AREA_FRACTION = 0.05

    def ocr(self, conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        return PdfReader.ocr_file(conn, file_path)

    @staticmethod
    def render_page_array(
        page: pymupdf.Page, clip: tuple[float, float, float, float] | None = None
    ) -> np.ndarray:
        import cv2
        import numpy as np

        pixmap = page.get_pixmap(clip=clip)
        image_bytes = pixmap.tobytes("png")
        return cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)

    @staticmethod
    def is_native_text(text: str) -> bool:
        stripped = text.strip()
        return (
            len(stripped) >= PdfReader.MIN_NATIVE_TEXT_CHARS
            and len(stripped.split()) >= PdfReader.MIN_NATIVE_TEXT_WORDS
        )

    @staticmethod
    def significant_image_blocks(
        page: pymupdf.Page,
    ) -> list[tuple[float, float, float, float]]:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return []

        bboxes = []
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 1:
                continue
            x0, y0, x1, y1 = block["bbox"]
            area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
            if area / page_area >= PdfReader.MIN_IMAGE_AREA_FRACTION:
                bboxes.append(block["bbox"])
        return bboxes

    @staticmethod
    def ocr_page(conn: sqlite3.Connection, page: pymupdf.Page) -> PageResult:
        """Classify a page as native, scanned, or mixed and extract accordingly.

        Native text is read directly from the PDF's text layer with no OCR at all.
        OCR only runs over the page (or, for a mixed page, just the embedded image
        regions) when the native text layer can't account for the page's content.
        """
        native_text = page.get_text()
        image_blocks = PdfReader.significant_image_blocks(page)

        if PdfReader.is_native_text(native_text) and not image_blocks:
            return PageResult(text=native_text.strip(), confidence=1.0, source="native")

        if PdfReader.is_native_text(native_text) and image_blocks:
            region_texts = []
            region_scores = []
            width = height = None
            for bbox in image_blocks:
                text, confidence, width, height = ImageReader.ocr_array(
                    conn, PdfReader.render_page_array(page, clip=bbox)
                )
                region_texts.append(text)
                region_scores.append(confidence)
            combined_text = "\n".join([native_text.strip(), *region_texts])
            combined_confidence = sum(region_scores) / len(region_scores)
            return PageResult(
                text=combined_text,
                confidence=combined_confidence,
                source="mixed",
                ocr_engine=Engine.name(),
                language=Engine.LANGUAGE,
                image_width=width,
                image_height=height,
            )

        text, confidence, width, height = ImageReader.ocr_array(
            conn, PdfReader.render_page_array(page)
        )
        return PageResult(
            text=text,
            confidence=confidence,
            source="ocr",
            ocr_engine=Engine.name(),
            language=Engine.LANGUAGE,
            image_width=width,
            image_height=height,
        )

    @staticmethod
    def ocr_file(conn: sqlite3.Connection, file_path: Path) -> list[PageResult]:
        import pymupdf

        with pymupdf.open(file_path) as doc:
            return [PdfReader.ocr_page(conn, page) for page in doc]


class PngReader(ImageReader):
    """A .png file - identical to `ImageReader` today, split out as a hook for
    PNG-specific handling later (e.g. transparency)."""


class JpgReader(ImageReader):
    """A .jpg/.jpeg file - identical to `ImageReader` today, split out as a hook
    for JPEG-specific handling later."""


class Readers:
    """The registered readers, by file suffix."""

    _BY_SUFFIX: dict[str, Reader] = {
        ".pdf": PdfReader(),
        ".png": PngReader(),
        ".jpg": JpgReader(),
        ".jpeg": JpgReader(),
    }

    @staticmethod
    def for_path(file_path: Path) -> Reader:
        return Readers._BY_SUFFIX[file_path.suffix.lower()]

    @staticmethod
    def is_supported(file_path: Path) -> bool:
        return file_path.suffix.lower() in Readers._BY_SUFFIX

    @staticmethod
    def iter_files(path: Path) -> Iterator[Path]:
        if path.is_file():
            if Readers.is_supported(path):
                yield path
            return
        for candidate in path.rglob("*"):
            if candidate.is_file() and Readers.is_supported(candidate):
                yield candidate

    @staticmethod
    def new_file_type_counts() -> dict[str, int]:
        """A zeroed `{file_type: count}` for every file type registered readers handle."""
        return dict.fromkeys((reader.file_type for reader in Readers._BY_SUFFIX.values()), 0)
