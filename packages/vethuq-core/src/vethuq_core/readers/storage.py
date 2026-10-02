"""How a document's extracted pages are persisted, independent of how they were read.

A `Reader` declares which `PageStorage` holds its pages, so the indexing pipeline
never branches on a file type to decide where pages go or how their confidence is
aggregated.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass

from vethuq_core.db.queries import Document as DocumentQuery


@dataclass(frozen=True)
class PageResult:
    """One extracted page, as handed to a `PageStorage` to persist."""

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


class PageStorage(ABC):
    """Persists one file type's pages and reads their confidences back."""

    # `confidence_metrics` is keyed by (file_type, process_type); a storage that doesn't
    # distinguish how its pages were produced files everything under this one.
    DEFAULT_PROCESS_TYPE = "ocr"

    @abstractmethod
    def store(self, conn: sqlite3.Connection, document_id: int, pages: list[PageResult]) -> None:
        """Replace a document's stored pages with freshly (re)extracted `pages`."""

    @abstractmethod
    def page_confidences(self, conn: sqlite3.Connection, document_id: int) -> list[float]:
        """Return the confidence of each page stored for `document_id`."""

    def confidences_by_process_type(
        self, conn: sqlite3.Connection, document_id: int
    ) -> dict[str, list[float]]:
        """Group stored page confidences by how each page was produced.

        Native pages run near-100% confidence while OCR/mixed pages don't, so
        `confidence_metrics` tracks each `process_type` separately. Storages whose
        pages are all produced the same way can keep this default.
        """
        confidences = self.page_confidences(conn, document_id)
        return {PageStorage.DEFAULT_PROCESS_TYPE: confidences} if confidences else {}


class PdfPageStorage(PageStorage):
    """Multi-page documents: one `pdf_pages` row per page."""

    def store(self, conn: sqlite3.Connection, document_id: int, pages: list[PageResult]) -> None:
        DocumentQuery.delete_pdf_pages(conn, document_id)
        DocumentQuery.insert_pdf_pages(
            conn,
            [
                (
                    document_id,
                    page_number,
                    page.text,
                    page.confidence,
                    page.source,
                    page.ocr_engine,
                    page.language,
                    page.image_width,
                    page.image_height,
                    *page.phase_columns(),
                )
                for page_number, page in enumerate(pages, start=1)
            ],
        )

    def page_confidences(self, conn: sqlite3.Connection, document_id: int) -> list[float]:
        return [
            row["confidence"]
            for row in DocumentQuery.get_page_confidences(conn, "pdf", document_id)
        ]

    def confidences_by_process_type(
        self, conn: sqlite3.Connection, document_id: int
    ) -> dict[str, list[float]]:
        grouped: dict[str, list[float]] = {}
        for row in DocumentQuery.get_pdf_page_sources(conn, document_id):
            grouped.setdefault(row["source"], []).append(row["confidence"])
        return grouped


class ImagePageStorage(PageStorage):
    """Single-image documents: one `image_pages` row per file."""

    def store(self, conn: sqlite3.Connection, document_id: int, pages: list[PageResult]) -> None:
        page = pages[0]
        DocumentQuery.delete_image_pages(conn, document_id)
        DocumentQuery.insert_image_page(
            conn,
            document_id,
            page.text,
            page.confidence,
            page.ocr_engine,
            page.language,
            page.image_width,
            page.image_height,
            *page.phase_columns(),
        )

    def page_confidences(self, conn: sqlite3.Connection, document_id: int) -> list[float]:
        return [
            row["confidence"]
            for row in DocumentQuery.get_page_confidences(conn, "image", document_id)
        ]
