"""SQL for the deeper OCR phases: per-page phase tracking and `document_phases`."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from vethuq_core.db.queries.documents import Document


class Ocr:
    _FIND_UNITS_SQL = {
        "pdf_pages": """
        SELECT p.id, p.ocr_phase, p.ocr_angles, p.page_number, p.source AS page_source,
               d.id AS document_id, d.document_id AS logical_document_id, d.file_path
        FROM pdf_pages p JOIN document_index d ON d.id = p.document_id
        WHERE d.status = 'indexed' AND d.reindex_pending = 0
          AND p.source != 'native' AND p.ocr_phase < ? AND d.source_id IN ({marks})
    """,
        "image_pages": """
        SELECT p.id, p.ocr_phase, p.ocr_angles, 1 AS page_number, 'ocr' AS page_source,
               d.id AS document_id, d.document_id AS logical_document_id, d.file_path
        FROM image_pages p JOIN document_index d ON d.id = p.document_id
        WHERE d.status = 'indexed' AND d.reindex_pending = 0
          AND p.ocr_phase < ? AND d.source_id IN ({marks})
    """,
    }
    _PAGE_SELECT_SQL = {
        "pdf_pages": (
            "SELECT ocr_text, confidence, ocr_phase, ocr_angles FROM pdf_pages WHERE id = ?"
        ),
        "image_pages": (
            "SELECT ocr_text, confidence, ocr_phase, ocr_angles FROM image_pages WHERE id = ?"
        ),
    }
    _PAGE_UPDATE_SQL = {
        "pdf_pages": (
            "UPDATE pdf_pages SET ocr_text = ?, noise_text = ?, norm_text = ?, confidence = ?, "
            "ocr_phase = ?, ocr_angles = ? WHERE id = ?"
        ),
        "image_pages": (
            "UPDATE image_pages SET ocr_text = ?, noise_text = ?, norm_text = ?, confidence = ?, "
            "ocr_phase = ?, ocr_angles = ? WHERE id = ?"
        ),
    }
    _PAGE_PHASE_DONE_SQL = {
        "pdf_pages": "UPDATE pdf_pages SET ocr_phase = MAX(ocr_phase, ?) WHERE id = ?",
        "image_pages": "UPDATE image_pages SET ocr_phase = MAX(ocr_phase, ?) WHERE id = ?",
    }
    _REMAINING_PAGES_SQL = {
        "pdf_pages": (
            "SELECT COUNT(*) FROM pdf_pages "
            "WHERE document_id = ? AND source != 'native' AND ocr_phase < ?"
        ),
        "image_pages": "SELECT COUNT(*) FROM image_pages WHERE document_id = ? AND ocr_phase < ?",
    }
    _PHASE_PROGRESS_SQL = {
        "pdf_pages": (
            "SELECT p.ocr_phase AS phase, COUNT(*) AS pages "
            "FROM pdf_pages p JOIN document_index d ON d.id = p.document_id "
            "WHERE d.status = 'indexed' AND d.reindex_pending = 0 AND p.source != 'native' "
            "AND d.source_id IN ({marks}) GROUP BY p.ocr_phase"
        ),
        "image_pages": (
            "SELECT p.ocr_phase AS phase, COUNT(*) AS pages "
            "FROM image_pages p JOIN document_index d ON d.id = p.document_id "
            "WHERE d.status = 'indexed' AND d.reindex_pending = 0 "
            "AND d.source_id IN ({marks}) GROUP BY p.ocr_phase"
        ),
    }
    _PHASE_PENDING_DOCS_SQL = {
        "pdf": (
            "SELECT COUNT(DISTINCT d.id) FROM pdf_pages p "
            "JOIN document_index d ON d.id = p.document_id "
            "WHERE d.status = 'indexed' AND d.reindex_pending = 0 AND p.source != 'native' "
            "AND p.ocr_phase < ? AND d.source_id IN ({marks})"
        ),
        "image": (
            "SELECT COUNT(DISTINCT d.id) FROM image_pages p "
            "JOIN document_index d ON d.id = p.document_id "
            "WHERE d.status = 'indexed' AND d.reindex_pending = 0 "
            "AND p.ocr_phase < ? AND d.source_id IN ({marks})"
        ),
    }

    @staticmethod
    def _marks(source_ids: Sequence[int]) -> str:
        return ",".join("?" * len(source_ids))

    @staticmethod
    def get_document_file_size(
        conn: sqlite3.Connection, document_index_id: int
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT file_path, file_size_bytes FROM document_index WHERE id = ?",
            (document_index_id,),
        ).fetchone()

    class Page:
        @staticmethod
        def list_short_of_phase(
            conn: sqlite3.Connection, table: str, max_phase: int, source_ids: Sequence[int]
        ) -> list[sqlite3.Row]:
            """Pages of `table` under `source_ids` whose `ocr_phase` is below `max_phase`."""
            return conn.execute(
                Ocr._FIND_UNITS_SQL[table].format(marks=Ocr._marks(source_ids)),
                (max_phase, *source_ids),
            ).fetchall()

        @staticmethod
        def get_text_row(conn: sqlite3.Connection, table: str, page_id: int) -> sqlite3.Row | None:
            return conn.execute(Ocr._PAGE_SELECT_SQL[table], (page_id,)).fetchone()

        @staticmethod
        def update_text(
            conn: sqlite3.Connection,
            table: str,
            page_id: int,
            ocr_text: str,
            confidence: float,
            ocr_phase: int,
            ocr_angles: str,
        ) -> None:
            conn.execute(
                Ocr._PAGE_UPDATE_SQL[table],
                (
                    ocr_text,
                    *Document.derived_text(ocr_text),
                    confidence,
                    ocr_phase,
                    ocr_angles,
                    page_id,
                ),
            )

        @staticmethod
        def mark_phase_done(conn: sqlite3.Connection, table: str, phase: int, page_id: int) -> None:
            conn.execute(Ocr._PAGE_PHASE_DONE_SQL[table], (phase, page_id))

        @staticmethod
        def count_short_of_phase(
            conn: sqlite3.Connection, table: str, document_id: int, phase: int
        ) -> int:
            return conn.execute(Ocr._REMAINING_PAGES_SQL[table], (document_id, phase)).fetchone()[0]

    class Phase:
        @staticmethod
        def list_progress_rows(
            conn: sqlite3.Connection, table: str, source_ids: Sequence[int]
        ) -> list[sqlite3.Row]:
            """`(phase, pages)` counts of eligible pages in `table` under `source_ids`."""
            return conn.execute(
                Ocr._PHASE_PROGRESS_SQL[table].format(marks=Ocr._marks(source_ids)),
                tuple(source_ids),
            ).fetchall()

        @staticmethod
        def count_documents_short_of(
            conn: sqlite3.Connection, file_type: str, phase: int, source_ids: Sequence[int]
        ) -> int:
            return conn.execute(
                Ocr._PHASE_PENDING_DOCS_SQL[file_type].format(marks=Ocr._marks(source_ids)),
                (phase, *source_ids),
            ).fetchone()[0]

        @staticmethod
        def start_document(
            conn: sqlite3.Connection, document_id: int, phase: int, started_at: str
        ) -> None:
            conn.execute(
                "INSERT OR IGNORE INTO document_phases "
                "(document_id, phase, started_at) VALUES (?, ?, ?)",
                (document_id, phase, started_at),
            )

        @staticmethod
        def get_document_work(
            conn: sqlite3.Connection, document_id: int, phase: int
        ) -> sqlite3.Row | None:
            return conn.execute(
                "SELECT duration_seconds, peak_memory_mb, cpu_percent FROM document_phases "
                "WHERE document_id = ? AND phase = ?",
                (document_id, phase),
            ).fetchone()

        @staticmethod
        def update_document_work(
            conn: sqlite3.Connection,
            document_id: int,
            phase: int,
            duration_seconds: float,
            peak_memory_mb: float,
            cpu_percent: float,
        ) -> None:
            conn.execute(
                "UPDATE document_phases SET duration_seconds = ?, peak_memory_mb = ?, "
                "cpu_percent = ? "
                "WHERE document_id = ? AND phase = ?",
                (duration_seconds, peak_memory_mb, cpu_percent, document_id, phase),
            )

        @staticmethod
        def get_document_completion(
            conn: sqlite3.Connection, document_id: int, phase: int
        ) -> sqlite3.Row | None:
            return conn.execute(
                "SELECT completed_at, duration_seconds, peak_memory_mb, cpu_percent "
                "FROM document_phases WHERE document_id = ? AND phase = ?",
                (document_id, phase),
            ).fetchone()

        @staticmethod
        def complete_document(
            conn: sqlite3.Connection, document_id: int, phase: int, completed_at: str
        ) -> None:
            conn.execute(
                "UPDATE document_phases SET completed_at = ?, indexed_at = ? "
                "WHERE document_id = ? AND phase = ?",
                (completed_at, completed_at, document_id, phase),
            )

    class Language:
        """The per-file OCR language passes (`document_languages`) and the page text they read."""

        _PAGES_SQL = {
            "pdf_pages": (
                "SELECT id, page_number, ocr_text, confidence, source, language, ocr_langs "
                "FROM pdf_pages WHERE document_id = ? ORDER BY page_number"
            ),
            "image_pages": (
                "SELECT id, 1 AS page_number, ocr_text, confidence, 'ocr' AS source, language, "
                "ocr_langs FROM image_pages WHERE document_id = ?"
            ),
        }
        _PAGE_LANGUAGES_SQL = {
            "pdf_pages": "UPDATE pdf_pages SET language = ?, ocr_langs = ? WHERE id = ?",
            "image_pages": "UPDATE image_pages SET language = ?, ocr_langs = ? WHERE id = ?",
        }

        @staticmethod
        def replace(
            conn: sqlite3.Connection,
            document_id: int,
            rows: Sequence[tuple[str, int, str, str, float | None]],
        ) -> None:
            """Set a file's passes to `rows`: `(language, position, status, source, confidence)`."""
            conn.execute("DELETE FROM document_languages WHERE document_id = ?", (document_id,))
            conn.executemany(
                "INSERT INTO document_languages "
                "(document_id, language, position, status, source, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(document_id, *row) for row in rows],
            )

        @staticmethod
        def get(conn: sqlite3.Connection, document_id: int) -> list[sqlite3.Row]:
            return conn.execute(
                "SELECT language, position, status, source, confidence, error_message, "
                "started_at, completed_at FROM document_languages "
                "WHERE document_id = ? ORDER BY position",
                (document_id,),
            ).fetchall()

        @staticmethod
        def update(
            conn: sqlite3.Connection,
            document_id: int,
            language: str,
            status: str,
            confidence: float | None,
            error_message: str | None,
            started_at: str | None,
            completed_at: str | None,
        ) -> None:
            conn.execute(
                "UPDATE document_languages SET status = ?, confidence = COALESCE(?, confidence), "
                "error_message = ?, started_at = COALESCE(?, started_at), "
                "completed_at = ? WHERE document_id = ? AND language = ?",
                (
                    status,
                    confidence,
                    error_message,
                    started_at,
                    completed_at,
                    document_id,
                    language,
                ),
            )

        @staticmethod
        def list_pending(conn: sqlite3.Connection, source_ids: Sequence[int]) -> list[sqlite3.Row]:
            """The next pending pass of every indexed file under `source_ids`, in queue order
            (earlier positions first, so every file gets its second language before any gets its
            third); a file's pass waits for the ones before it."""
            if not source_ids:
                return []
            return conn.execute(
                "SELECT dl.document_id, dl.language, dl.position, dl.source AS choice_source, "
                "d.file_path, d.file_type, d.source_id, d.document_id AS logical_document_id "
                "FROM document_languages dl JOIN document_index d ON d.id = dl.document_id "
                "WHERE dl.status = 'pending' AND d.status = 'indexed' AND d.reindex_pending = 0 "
                f"AND d.source_id IN ({Ocr._marks(source_ids)}) "
                "AND NOT EXISTS (SELECT 1 FROM document_languages e "
                "WHERE e.document_id = dl.document_id AND e.position < dl.position "
                "AND e.status IN ('pending', 'processing')) "
                "ORDER BY dl.position, d.id",
                tuple(source_ids),
            ).fetchall()

        @staticmethod
        def count_pending(conn: sqlite3.Connection, source_ids: Sequence[int]) -> int:
            return len(Ocr.Language.list_pending(conn, source_ids))

        @staticmethod
        def list_pages(conn: sqlite3.Connection, table: str, document_id: int) -> list[sqlite3.Row]:
            return conn.execute(Ocr.Language._PAGES_SQL[table], (document_id,)).fetchall()

        @staticmethod
        def update_page_languages(
            conn: sqlite3.Connection, table: str, page_id: int, language: str, ocr_langs: str
        ) -> None:
            conn.execute(Ocr.Language._PAGE_LANGUAGES_SQL[table], (language, ocr_langs, page_id))

        @staticmethod
        def reset_processing(conn: sqlite3.Connection) -> int:
            """Put passes a crashed run left 'processing' back to 'pending'; returns how many."""
            cursor = conn.execute(
                "UPDATE document_languages SET status = 'pending', started_at = NULL "
                "WHERE status = 'processing'"
            )
            return cursor.rowcount
