"""SQL for the `documents`, `document_index`, and per-file-type `*_pages` tables."""

from __future__ import annotations

import sqlite3


class Document:
    # The pages table a `document_index.file_type`'s text is stored in.
    PAGE_TABLES = {"pdf": "pdf_pages", "image": "image_pages", "csv": "csv_pages"}

    @staticmethod
    def get_id_for_index_row(
        conn: sqlite3.Connection, document_index_id: int
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT document_id FROM document_index WHERE id = ?", (document_index_id,)
        ).fetchone()

    @staticmethod
    def list_index_peers(
        conn: sqlite3.Connection, document_id: int, exclude_id: int
    ) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT id FROM document_index WHERE document_id = ? AND id != ? ORDER BY id ASC",
            (document_id, exclude_id),
        ).fetchall()

    @staticmethod
    def reassign_pdf_pages(
        conn: sqlite3.Connection, old_document_index_id: int, new_document_index_id: int
    ) -> None:
        conn.execute(
            "UPDATE pdf_pages SET document_id = ? WHERE document_id = ?",
            (new_document_index_id, old_document_index_id),
        )

    @staticmethod
    def reassign_image_pages(
        conn: sqlite3.Connection, old_document_index_id: int, new_document_index_id: int
    ) -> None:
        conn.execute(
            "UPDATE image_pages SET document_id = ? WHERE document_id = ?",
            (new_document_index_id, old_document_index_id),
        )

    @staticmethod
    def reassign_csv_pages(
        conn: sqlite3.Connection, old_document_index_id: int, new_document_index_id: int
    ) -> None:
        conn.execute(
            "UPDATE csv_pages SET document_id = ? WHERE document_id = ?",
            (new_document_index_id, old_document_index_id),
        )

    @staticmethod
    def index_references_document(conn: sqlite3.Connection, document_id: int) -> bool:
        row = conn.execute(
            "SELECT 1 FROM document_index WHERE document_id = ? LIMIT 1", (document_id,)
        ).fetchone()
        return row is not None

    @staticmethod
    def delete(conn: sqlite3.Connection, document_id: int) -> None:
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    @staticmethod
    def insert(conn: sqlite3.Connection, created_at: str) -> int:
        cursor = conn.execute("INSERT INTO documents (created_at) VALUES (?)", (created_at,))
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @staticmethod
    def delete_phases(conn: sqlite3.Connection, document_id: int) -> None:
        conn.execute("DELETE FROM document_phases WHERE document_id = ?", (document_id,))

    @staticmethod
    def list_index_rows_for_sources(
        conn: sqlite3.Connection, source_ids: list[int]
    ) -> list[sqlite3.Row]:
        placeholders = ",".join("?" * len(source_ids))
        return conn.execute(
            f"SELECT id, document_id FROM document_index WHERE source_id IN ({placeholders})",
            source_ids,
        ).fetchall()

    @staticmethod
    def delete_pdf_pages(conn: sqlite3.Connection, document_index_id: int) -> None:
        conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_index_id,))

    @staticmethod
    def delete_image_pages(conn: sqlite3.Connection, document_index_id: int) -> None:
        conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_index_id,))

    @staticmethod
    def delete_csv_pages(conn: sqlite3.Connection, document_index_id: int) -> None:
        conn.execute("DELETE FROM csv_pages WHERE document_id = ?", (document_index_id,))

    @staticmethod
    def delete_index_for_sources(conn: sqlite3.Connection, source_ids: list[int]) -> None:
        placeholders = ",".join("?" * len(source_ids))
        conn.execute(f"DELETE FROM document_index WHERE source_id IN ({placeholders})", source_ids)

    @staticmethod
    def list_expired_removed_index_rows(conn: sqlite3.Connection, cutoff: str) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT id FROM document_index "
            "WHERE status = 'removed' AND removed_at IS NOT NULL AND removed_at <= ?",
            (cutoff,),
        ).fetchall()

    @staticmethod
    def list_index_rows_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
        placeholders = ",".join("?" * len(ids))
        return conn.execute(
            f"SELECT document_id FROM document_index WHERE id IN ({placeholders})", ids
        ).fetchall()

    @staticmethod
    def delete_index_by_ids(conn: sqlite3.Connection, ids: list[int]) -> None:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM document_index WHERE id IN ({placeholders})", ids)

    @staticmethod
    def find_duplicate_index(
        conn: sqlite3.Connection, sha256: str, exclude_id: int
    ) -> sqlite3.Row | None:
        """Return the earliest-indexed `document_index` row (id, document_id) matching `sha256`."""
        return conn.execute(
            "SELECT id, document_id FROM document_index "
            "WHERE sha256 = ? AND id != ? AND status = 'indexed' ORDER BY id ASC LIMIT 1",
            (sha256, exclude_id),
        ).fetchone()

    @staticmethod
    def get_index_by_path(conn: sqlite3.Connection, file_path: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT id, document_id, sha256, status FROM document_index WHERE file_path = ?",
            (file_path,),
        ).fetchone()

    @staticmethod
    def get_index_id_by_path(conn: sqlite3.Connection, file_path: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT id FROM document_index WHERE file_path = ?", (file_path,)
        ).fetchone()

    @staticmethod
    def upsert_index(
        conn: sqlite3.Connection,
        source_id: int,
        document_id: int,
        file_path: str,
        file_type: str,
        started_at: str,
        file_size_bytes: int,
        sha256: str,
        mtime: float,
        created_at: str,
        modified_at: str,
    ) -> bool:
        """Atomically claim `file_path`'s row for processing, setting status='processing'.

        The `WHERE document_index.status != 'processing'` guard makes this a real
        claim rather than a plain upsert: if the row already has status=
        'processing' (another concurrently-running index run already claimed it),
        SQLite's UPSERT treats the conflict as a no-op instead of applying
        `DO UPDATE`, and this returns False. The caller must then leave the row
        untouched - whichever run holds the claim owns finishing it. Returns True
        when the claim is won, whether that's a fresh row (plain insert, no
        conflict) or resetting an existing non-'processing' one.
        """
        cursor = conn.execute(
            """
            INSERT INTO document_index
                (source_id, document_id, file_path, file_type, status, started_at,
                 file_size_bytes, sha256, mtime, created_at, modified_at)
            VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                document_id = excluded.document_id,
                status = 'processing', error_message = NULL, indexed_at = NULL,
                started_at = excluded.started_at, completed_at = NULL,
                file_size_bytes = excluded.file_size_bytes, sha256 = excluded.sha256,
                mtime = excluded.mtime, created_at = excluded.created_at,
                modified_at = excluded.modified_at
            WHERE document_index.status != 'processing'
            """,
            (
                source_id,
                document_id,
                file_path,
                file_type,
                started_at,
                file_size_bytes,
                sha256,
                mtime,
                created_at,
                modified_at,
            ),
        )
        return cursor.rowcount > 0

    @staticmethod
    def fail_stuck_processing_index(conn: sqlite3.Connection, message: str, now: str) -> None:
        """Reset every row still claimed ('processing') back to 'error', so it's retried.

        Called only once the caller is certain nothing is still actively working
        on these rows (a crashed/force-killed run being reconciled at the next
        start, or right after force-killing one that missed its stop timeout) -
        otherwise a claim (see `upsert_index`) would hold a row in 'processing'
        forever, since nothing else ever moves it to 'indexed' or 'error'.
        """
        conn.execute(
            "UPDATE document_index SET status = 'error', error_message = ?, completed_at = ? "
            "WHERE status = 'processing'",
            (message, now),
        )

    @staticmethod
    def list_tracked_index_rows(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT id, document_id, file_path, sha256 FROM document_index "
            "WHERE source_id = ? AND status != 'removed'",
            (source_id,),
        ).fetchall()

    @staticmethod
    def update_index_path(
        conn: sqlite3.Connection,
        row_id: int,
        new_path: str,
        mtime: float,
        file_size_bytes: int,
        created_at: str,
        modified_at: str,
    ) -> None:
        conn.execute(
            "UPDATE document_index SET file_path = ?, mtime = ?, file_size_bytes = ?, "
            "created_at = ?, modified_at = ? WHERE id = ?",
            (new_path, mtime, file_size_bytes, created_at, modified_at, row_id),
        )

    @staticmethod
    def mark_index_removed(conn: sqlite3.Connection, row_id: int, removed_at: str) -> None:
        conn.execute(
            "UPDATE document_index SET status = 'removed', removed_at = ? WHERE id = ?",
            (removed_at, row_id),
        )

    @staticmethod
    def mark_indexed(conn: sqlite3.Connection, document_id: int, now: str) -> None:
        conn.execute(
            "UPDATE document_index SET status = 'indexed', indexed_at = ?, completed_at = ? "
            "WHERE id = ?",
            (now, now, document_id),
        )

    @staticmethod
    def mark_error(conn: sqlite3.Connection, document_id: int, message: str, now: str) -> None:
        conn.execute(
            "UPDATE document_index SET status = 'error', error_message = ?, completed_at = ? "
            "WHERE id = ?",
            (message, now, document_id),
        )

    @staticmethod
    def get_index_metrics_stats(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row:
        row = conn.execute(
            "SELECT started_at, completed_at, peak_memory_mb, cpu_percent, file_size_bytes "
            "FROM document_index WHERE id = ?",
            (document_id,),
        ).fetchone()
        assert row is not None
        return row

    @staticmethod
    def get_page_confidences(
        conn: sqlite3.Connection, file_type: str, document_id: int
    ) -> list[sqlite3.Row]:
        table = Document.PAGE_TABLES[file_type]
        return conn.execute(
            f"SELECT confidence FROM {table} WHERE document_id = ?", (document_id,)
        ).fetchall()

    @staticmethod
    def get_page_sources(
        conn: sqlite3.Connection, file_type: str, document_id: int
    ) -> list[sqlite3.Row]:
        """`(confidence, source)` per page, for file types whose pages record a `source`."""
        table = Document.PAGE_TABLES[file_type]
        return conn.execute(
            f"SELECT confidence, source FROM {table} WHERE document_id = ?", (document_id,)
        ).fetchall()

    @staticmethod
    def get_index_pending_check(conn: sqlite3.Connection, file_path: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT status, mtime, file_size_bytes, sha256 FROM document_index WHERE file_path = ?",
            (file_path,),
        ).fetchone()

    @staticmethod
    def update_index_retry_stats(
        conn: sqlite3.Connection,
        document_id: int,
        retry_count: int,
        peak_memory_mb: float,
        cpu_percent: float,
    ) -> None:
        conn.execute(
            "UPDATE document_index SET retry_count = ?, peak_memory_mb = ?, cpu_percent = ? "
            "WHERE id = ?",
            (retry_count, peak_memory_mb, cpu_percent, document_id),
        )

    @staticmethod
    def insert_pdf_pages(conn: sqlite3.Connection, rows: list[tuple]) -> None:
        conn.executemany(
            "INSERT INTO pdf_pages "
            "(document_id, page_number, ocr_text, confidence, source, "
            "ocr_engine, language, image_width, image_height, ocr_phase, ocr_angles) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    @staticmethod
    def insert_image_page(
        conn: sqlite3.Connection,
        document_id: int,
        ocr_text: str,
        confidence: float,
        ocr_engine: str | None,
        language: str | None,
        image_width: int | None,
        image_height: int | None,
        ocr_phase: int,
        ocr_angles: str,
    ) -> None:
        conn.execute(
            "INSERT INTO image_pages "
            "(document_id, ocr_text, confidence, ocr_engine, language, "
            "image_width, image_height, ocr_phase, ocr_angles) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document_id,
                ocr_text,
                confidence,
                ocr_engine,
                language,
                image_width,
                image_height,
                ocr_phase,
                ocr_angles,
            ),
        )

    @staticmethod
    def insert_csv_page(
        conn: sqlite3.Connection,
        document_id: int,
        ocr_text: str,
        confidence: float,
        source: str,
        encoding: str | None,
        delimiter: str | None,
        row_count: int,
        column_count: int,
    ) -> None:
        conn.execute(
            "INSERT INTO csv_pages (document_id, ocr_text, confidence, source, encoding, "
            "delimiter, row_count, column_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document_id,
                ocr_text,
                confidence,
                source,
                encoding,
                delimiter,
                row_count,
                column_count,
            ),
        )

    @staticmethod
    def count_index_by_status(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
        """`(status, count)` of `source_id`'s `document_index` rows, one row per status."""
        return conn.execute(
            "SELECT status, COUNT(*) AS count FROM document_index WHERE source_id = ? "
            "GROUP BY status",
            (source_id,),
        ).fetchall()

    @staticmethod
    def get_result_rows(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
        """Return one row per `document_index` row for `source_id`, with duplicate linkage.

        `canonical_id` is whichever `document_index` row sharing this one's
        `document_id` actually carries OCR pages of its own (itself, if it does)
        - duplicates are detected globally, so that carrier may belong to a
        different source than `source_id`.
        """
        return conn.execute(
            "SELECT di.id AS id, di.file_path AS file_path, di.file_type AS file_type, "
            "di.status AS status, di.error_message AS error_message, "
            "di.started_at AS started_at, di.completed_at AS completed_at, "
            "COALESCE("
            "  (SELECT peer.id FROM document_index peer "
            "   WHERE peer.document_id = di.document_id AND ("
            "     EXISTS (SELECT 1 FROM pdf_pages WHERE document_id = peer.id) "
            "     OR EXISTS (SELECT 1 FROM image_pages WHERE document_id = peer.id) "
            "     OR EXISTS (SELECT 1 FROM csv_pages WHERE document_id = peer.id)"
            "   ) LIMIT 1), "
            "  di.id"
            ") AS canonical_id, "
            "(SELECT peer.file_path FROM document_index peer "
            " WHERE peer.document_id = di.document_id AND peer.id != di.id AND ("
            "   EXISTS (SELECT 1 FROM pdf_pages WHERE document_id = peer.id) "
            "   OR EXISTS (SELECT 1 FROM image_pages WHERE document_id = peer.id) "
            "   OR EXISTS (SELECT 1 FROM csv_pages WHERE document_id = peer.id)"
            " ) LIMIT 1) AS duplicate_of_path "
            "FROM document_index di "
            "WHERE di.source_id = ? ORDER BY di.file_path",
            (source_id,),
        ).fetchall()

    @staticmethod
    def search_indexed_pdf_pages(conn: sqlite3.Connection, like_pattern: str) -> list[sqlite3.Row]:
        """Return indexed `pdf_pages` rows whose `ocr_text` matches `like_pattern`.

        `like_pattern` is a caller-escaped `LIKE` pattern (see
        `vethuq_core.search.Search._like_pattern`), matched against `pdf_pages_fts` -
        a trigram-tokenized FTS5 index kept in sync with `pdf_pages` by triggers
        (see `vethuq_core.db.connection`) - rather than `pdf_pages` itself, so the
        match is resolved through the trigram index instead of a full table scan.
        """
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, pp.ocr_text AS ocr_text, "
            "pp.page_number AS page_number, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM pdf_pages_fts "
            "JOIN pdf_pages pp ON pp.id = pdf_pages_fts.rowid "
            "JOIN document_index carrier ON carrier.id = pp.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE pdf_pages_fts.ocr_text LIKE ? ESCAPE '\\' "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
            "ORDER BY di.file_path, pp.page_number",
            (like_pattern,),
        ).fetchall()

    @staticmethod
    def search_indexed_image_pages(
        conn: sqlite3.Connection, like_pattern: str
    ) -> list[sqlite3.Row]:
        """Like `search_indexed_pdf_pages`, but for `image_pages`/`image_pages_fts`."""
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, ip.ocr_text AS ocr_text, "
            "NULL AS page_number, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM image_pages_fts "
            "JOIN image_pages ip ON ip.id = image_pages_fts.rowid "
            "JOIN document_index carrier ON carrier.id = ip.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE image_pages_fts.ocr_text LIKE ? ESCAPE '\\' "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
            "ORDER BY di.file_path",
            (like_pattern,),
        ).fetchall()

    @staticmethod
    def search_indexed_csv_pages(conn: sqlite3.Connection, like_pattern: str) -> list[sqlite3.Row]:
        """Like `search_indexed_pdf_pages`, but for `csv_pages`/`csv_pages_fts`."""
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, cp.ocr_text AS ocr_text, "
            "NULL AS page_number, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM csv_pages_fts "
            "JOIN csv_pages cp ON cp.id = csv_pages_fts.rowid "
            "JOIN document_index carrier ON carrier.id = cp.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE csv_pages_fts.ocr_text LIKE ? ESCAPE '\\' "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'csv' "
            "ORDER BY di.file_path",
            (like_pattern,),
        ).fetchall()

    @staticmethod
    def get_pdf_page_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT document_id, COUNT(*) AS total FROM pdf_pages GROUP BY document_id"
        ).fetchall()

    @staticmethod
    def refresh_file_path(conn: sqlite3.Connection, document_id: int) -> None:
        """Point a `documents` row's `file_path` at its earliest non-'removed' copy (or NULL)."""
        conn.execute(
            "UPDATE documents SET file_path = ("
            "SELECT file_path FROM document_index "
            "WHERE document_id = documents.id AND status != 'removed' "
            "ORDER BY id ASC LIMIT 1) WHERE id = ?",
            (document_id,),
        )
