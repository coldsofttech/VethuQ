"""Seeding helpers shared by the search tests: sources, documents and OCR pages."""

import sqlite3
from datetime import UTC, datetime

from vethuq_core.leet import Leet


class SearchData:
    @staticmethod
    def add_source(conn: sqlite3.Connection, path: str = "/docs") -> int:
        now = datetime.now(UTC).isoformat()
        cursor = conn.execute(
            "INSERT INTO sources (path, source_type, status, added_at) "
            "VALUES (?, 'folder', 'indexed', ?)",
            (path, now),
        )
        conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @staticmethod
    def add_document(
        conn: sqlite3.Connection,
        source_id: int,
        file_path: str,
        file_type: str = "pdf",
        status: str = "indexed",
        document_id: int | None = None,
    ) -> int:
        """Insert a `document_index` row, creating a fresh logical `documents` row unless
        `document_id` (another row's logical document, to link this one as sharing its
        content) is given."""
        if document_id is None:
            document_id = conn.execute(
                "INSERT INTO documents (created_at) VALUES (?)",
                (datetime.now(UTC).isoformat(),),
            ).lastrowid
        cursor = conn.execute(
            "INSERT INTO document_index "
            "(source_id, document_id, file_path, file_type, status) VALUES (?, ?, ?, ?, ?)",
            (source_id, document_id, file_path, file_type, status),
        )
        conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @staticmethod
    def add_pdf_page(
        conn: sqlite3.Connection, document_id: int, page_number: int, text: str
    ) -> None:
        conn.execute(
            "INSERT INTO pdf_pages (document_id, page_number, ocr_text, noise_text, confidence) "
            "VALUES (?, ?, ?, ?, 0.95)",
            (document_id, page_number, text, Leet.skeleton(text)),
        )
        conn.commit()

    @staticmethod
    def add_image_page(conn: sqlite3.Connection, document_id: int, text: str) -> None:
        conn.execute(
            "INSERT INTO image_pages (document_id, ocr_text, noise_text, confidence) "
            "VALUES (?, ?, ?, 0.95)",
            (document_id, text, Leet.skeleton(text)),
        )
        conn.commit()

    @staticmethod
    def seed_page(conn: sqlite3.Connection, text: str, path: str = "/docs/museum.pdf") -> int:
        """One indexed single-page PDF holding `text`, in its own source."""
        source_id = SearchData.add_source(conn, path=path + ".source")
        document_id = SearchData.add_document(conn, source_id, path)
        SearchData.add_pdf_page(conn, document_id, 1, text)
        return document_id
