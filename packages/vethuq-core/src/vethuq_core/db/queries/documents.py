"""SQL for the `documents`, `document_index`, `pdf_pages`, and `image_pages` tables."""

from __future__ import annotations

import sqlite3


class Document:
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
    def mark_unsupported(
        conn: sqlite3.Connection, document_id: int, message: str, now: str
    ) -> None:
        conn.execute(
            "UPDATE document_index SET status = 'unsupported', error_message = ?, "
            "completed_at = ? WHERE id = ?",
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
        table = "pdf_pages" if file_type == "pdf" else "image_pages"
        return conn.execute(
            f"SELECT confidence FROM {table} WHERE document_id = ?", (document_id,)
        ).fetchall()

    @staticmethod
    def get_pdf_page_sources(conn: sqlite3.Connection, document_id: int) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT confidence, source FROM pdf_pages WHERE document_id = ?", (document_id,)
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
            "(document_id, page_number, ocr_text, char_count, confidence, source, "
            "ocr_engine, language, image_width, image_height, ocr_phase, ocr_angles) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    @staticmethod
    def insert_image_page(
        conn: sqlite3.Connection,
        document_id: int,
        ocr_text: str,
        char_count: int,
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
            "(document_id, ocr_text, char_count, confidence, ocr_engine, language, "
            "image_width, image_height, ocr_phase, ocr_angles) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document_id,
                ocr_text,
                char_count,
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
            "     OR EXISTS (SELECT 1 FROM image_pages WHERE document_id = peer.id)"
            "   ) LIMIT 1), "
            "  di.id"
            ") AS canonical_id, "
            "(SELECT peer.file_path FROM document_index peer "
            " WHERE peer.document_id = di.document_id AND peer.id != di.id AND ("
            "   EXISTS (SELECT 1 FROM pdf_pages WHERE document_id = peer.id) "
            "   OR EXISTS (SELECT 1 FROM image_pages WHERE document_id = peer.id)"
            " ) LIMIT 1) AS duplicate_of_path "
            "FROM document_index di "
            "WHERE di.source_id = ? ORDER BY di.file_path",
            (source_id,),
        ).fetchall()

    @staticmethod
    def list_source_file_rows(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
        """One row per `document_index` row of `source_id`, with the detail `source list` shows.

        `canonical_id` and `duplicate_of_path` follow the same rule as `get_result_rows`.
        """
        return conn.execute(
            "SELECT di.id AS id, di.document_id AS document_id, di.file_path AS file_path, "
            "di.file_type AS file_type, di.status AS status, "
            "di.error_message AS error_message, di.file_size_bytes AS file_size_bytes, "
            "di.started_at AS started_at, di.completed_at AS completed_at, "
            "di.indexed_at AS indexed_at, di.retry_count AS retry_count, "
            "COALESCE("
            "  (SELECT peer.id FROM document_index peer "
            "   WHERE peer.document_id = di.document_id AND ("
            "     EXISTS (SELECT 1 FROM pdf_pages WHERE document_id = peer.id) "
            "     OR EXISTS (SELECT 1 FROM image_pages WHERE document_id = peer.id)"
            "   ) LIMIT 1), "
            "  di.id"
            ") AS canonical_id, "
            "(SELECT peer.file_path FROM document_index peer "
            " WHERE peer.document_id = di.document_id AND peer.id != di.id AND ("
            "   EXISTS (SELECT 1 FROM pdf_pages WHERE document_id = peer.id) "
            "   OR EXISTS (SELECT 1 FROM image_pages WHERE document_id = peer.id)"
            " ) LIMIT 1) AS duplicate_of_path "
            "FROM document_index di "
            "WHERE di.source_id = ? ORDER BY di.file_path",
            (source_id,),
        ).fetchall()

    @staticmethod
    def list_page_ocr_state(
        conn: sqlite3.Connection, file_type: str, document_id: int
    ) -> list[sqlite3.Row]:
        """`(ocr_phase, ocr_angles, confidence)` of every stored page of `document_id`."""
        table = "pdf_pages" if file_type == "pdf" else "image_pages"
        return conn.execute(
            f"SELECT ocr_phase, ocr_angles, confidence FROM {table} WHERE document_id = ?",
            (document_id,),
        ).fetchall()

    @staticmethod
    def list_phase_rows(conn: sqlite3.Connection, logical_document_id: int) -> list[sqlite3.Row]:
        """The deeper-phase (2+) `document_phases` rows of a logical document, in phase order."""
        return conn.execute(
            "SELECT phase, started_at, completed_at, indexed_at, duration_seconds "
            "FROM document_phases WHERE document_id = ? ORDER BY phase",
            (logical_document_id,),
        ).fetchall()

    @staticmethod
    def search_indexed_pdf_pages(
        conn: sqlite3.Connection, like_pattern: str, match_expr: str | None = None
    ) -> list[sqlite3.Row]:
        """Return indexed `pdf_pages` rows that may hold a substring match.

        Resolved through `pdf_pages_trigram` - a trigram-tokenized FTS5 index kept
        in sync with `pdf_pages` by triggers (see `vethuq_core.db.connection`) -
        rather than a full table scan. `match_expr` (see
        `SearchEngineHelpers.trigram_match`) is the primary path: an FTS5 `MATCH`
        phrase. Only when it is None (a query under three characters, which the
        trigram index can't serve) is the caller-escaped `like_pattern` (see
        `SearchEngineHelpers.like_pattern`) used, as an explicit `LIKE` fallback.
        """
        where = (
            "pdf_pages_trigram MATCH ? "
            if match_expr is not None
            else "pdf_pages_trigram.ocr_text LIKE ? ESCAPE '\\' "
        )
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, pp.ocr_text AS ocr_text, "
            "pp.page_number AS page_number, pp.source AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM pdf_pages_trigram "
            "JOIN pdf_pages pp ON pp.id = pdf_pages_trigram.rowid "
            "JOIN document_index carrier ON carrier.id = pp.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            f"WHERE {where}"
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
            "ORDER BY di.file_path, pp.page_number",
            (match_expr if match_expr is not None else like_pattern,),
        ).fetchall()

    @staticmethod
    def search_indexed_image_pages(
        conn: sqlite3.Connection, like_pattern: str, match_expr: str | None = None
    ) -> list[sqlite3.Row]:
        """Like `search_indexed_pdf_pages`, but for `image_pages`/`image_pages_trigram`."""
        where = (
            "image_pages_trigram MATCH ? "
            if match_expr is not None
            else "image_pages_trigram.ocr_text LIKE ? ESCAPE '\\' "
        )
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, ip.ocr_text AS ocr_text, "
            "NULL AS page_number, 'ocr' AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM image_pages_trigram "
            "JOIN image_pages ip ON ip.id = image_pages_trigram.rowid "
            "JOIN document_index carrier ON carrier.id = ip.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            f"WHERE {where}"
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
            "ORDER BY di.file_path",
            (match_expr if match_expr is not None else like_pattern,),
        ).fetchall()

    @staticmethod
    def search_lexical_pdf_pages(conn: sqlite3.Connection, match_expr: str) -> list[sqlite3.Row]:
        """Return indexed `pdf_pages` rows matching the trigram `match_expr`, best match first.

        Queries `pdf_pages_trigram` (substring matching, case folded) and ranks by
        BM25 as `score` (higher is better). Otherwise shaped like
        `search_indexed_pdf_pages`.
        """
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, pp.ocr_text AS ocr_text, "
            "-bm25(pdf_pages_trigram) AS score, "
            "pp.page_number AS page_number, pp.source AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM pdf_pages_trigram "
            "JOIN pdf_pages pp ON pp.id = pdf_pages_trigram.rowid "
            "JOIN document_index carrier ON carrier.id = pp.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE pdf_pages_trigram MATCH ? "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
            "ORDER BY score DESC, di.file_path, pp.page_number",
            (match_expr,),
        ).fetchall()

    @staticmethod
    def search_lexical_image_pages(conn: sqlite3.Connection, match_expr: str) -> list[sqlite3.Row]:
        """Like `search_lexical_pdf_pages`, but for `image_pages`/`image_pages_trigram`."""
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, ip.ocr_text AS ocr_text, "
            "-bm25(image_pages_trigram) AS score, "
            "NULL AS page_number, 'ocr' AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM image_pages_trigram "
            "JOIN image_pages ip ON ip.id = image_pages_trigram.rowid "
            "JOIN document_index carrier ON carrier.id = ip.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE image_pages_trigram MATCH ? "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
            "ORDER BY score DESC, di.file_path",
            (match_expr,),
        ).fetchall()

    @staticmethod
    def search_candidate_pdf_pages(
        conn: sqlite3.Connection, match_expr: str | None
    ) -> list[sqlite3.Row]:
        """Return indexed `pdf_pages` rows that may hold a fuzzy match.

        Shaped like `search_indexed_pdf_pages`.

        `match_expr` is an FTS5 expression over the trigram index `pdf_pages_trigram`
        that every page that could match satisfies (a superset the caller then
        verifies); None means no such narrowing is possible, so every indexed
        page is returned. The expression is built by the caller from word
        characters only, never from raw user input.
        """
        source = (
            "pdf_pages_trigram JOIN pdf_pages pp ON pp.id = pdf_pages_trigram.rowid "
            if match_expr is not None
            else "pdf_pages pp "
        )
        where = "pdf_pages_trigram MATCH ? AND " if match_expr is not None else ""
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, pp.ocr_text AS ocr_text, "
            "pp.page_number AS page_number, pp.source AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            f"FROM {source}"
            "JOIN document_index carrier ON carrier.id = pp.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            f"WHERE {where}"
            "di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
            "ORDER BY di.file_path, pp.page_number",
            (match_expr,) if match_expr is not None else (),
        ).fetchall()

    @staticmethod
    def search_candidate_image_pages(
        conn: sqlite3.Connection, match_expr: str | None
    ) -> list[sqlite3.Row]:
        """Like `search_candidate_pdf_pages`, but for `image_pages`/`image_pages_trigram`."""
        source = (
            "image_pages_trigram JOIN image_pages ip ON ip.id = image_pages_trigram.rowid "
            if match_expr is not None
            else "image_pages ip "
        )
        where = "image_pages_trigram MATCH ? AND " if match_expr is not None else ""
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, ip.ocr_text AS ocr_text, "
            "NULL AS page_number, 'ocr' AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            f"FROM {source}"
            "JOIN document_index carrier ON carrier.id = ip.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            f"WHERE {where}"
            "di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
            "ORDER BY di.file_path",
            (match_expr,) if match_expr is not None else (),
        ).fetchall()

    @staticmethod
    def search_fulltext_pdf_pages(conn: sqlite3.Connection, match_expr: str) -> list[sqlite3.Row]:
        """Return indexed `pdf_pages` rows matching the FTS5 `match_expr`, best match first.

        Queries `pdf_pages_words` - the word-based (`unicode61` + `porter`) index kept in sync
        with `pdf_pages` by triggers - with `MATCH`. `highlighted_text` is the page's text
        with every matched word wrapped in control characters 0x02...0x03 (FTS5's own
        `highlight()`, so stemmed and prefix matches are marked exactly as the index
        matched them), and `score` is the negated BM25 rank (higher is better).
        Otherwise shaped like `search_indexed_pdf_pages`.
        """
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, "
            "highlight(pdf_pages_words, 0, char(2), char(3)) AS highlighted_text, "
            "-bm25(pdf_pages_words) AS score, "
            "pp.page_number AS page_number, pp.source AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM pdf_pages_words "
            "JOIN pdf_pages pp ON pp.id = pdf_pages_words.rowid "
            "JOIN document_index carrier ON carrier.id = pp.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE pdf_pages_words MATCH ? "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
            "ORDER BY score DESC, di.file_path, pp.page_number",
            (match_expr,),
        ).fetchall()

    @staticmethod
    def search_fulltext_image_pages(conn: sqlite3.Connection, match_expr: str) -> list[sqlite3.Row]:
        """Like `search_fulltext_pdf_pages`, but for `image_pages`/`image_pages_words`."""
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, "
            "highlight(image_pages_words, 0, char(2), char(3)) AS highlighted_text, "
            "-bm25(image_pages_words) AS score, "
            "NULL AS page_number, 'ocr' AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM image_pages_words "
            "JOIN image_pages ip ON ip.id = image_pages_words.rowid "
            "JOIN document_index carrier ON carrier.id = ip.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE image_pages_words MATCH ? "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
            "ORDER BY score DESC, di.file_path",
            (match_expr,),
        ).fetchall()

    @staticmethod
    def search_proximity_pdf_pages(conn: sqlite3.Connection, match_expr: str) -> list[sqlite3.Row]:
        """Return indexed `pdf_pages` rows matching the FTS5 `NEAR` expression `match_expr`.

        Like `search_fulltext_pdf_pages` but without the text: `page_id` (the
        `pdf_pages` row id, to pass to `get_pdf_term_highlights`) and `score` (the
        negated BM25 rank, higher is better) come back instead.
        """
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, pp.id AS page_id, "
            "-bm25(pdf_pages_words) AS score, "
            "pp.page_number AS page_number, pp.source AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM pdf_pages_words "
            "JOIN pdf_pages pp ON pp.id = pdf_pages_words.rowid "
            "JOIN document_index carrier ON carrier.id = pp.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE pdf_pages_words MATCH ? "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
            "ORDER BY score DESC, di.file_path, pp.page_number",
            (match_expr,),
        ).fetchall()

    @staticmethod
    def search_proximity_image_pages(
        conn: sqlite3.Connection, match_expr: str
    ) -> list[sqlite3.Row]:
        """Like `search_proximity_pdf_pages`, but for `image_pages`/`image_pages_words`."""
        return conn.execute(
            "SELECT di.id AS document_id, di.file_path AS file_path, ip.id AS page_id, "
            "-bm25(image_pages_words) AS score, "
            "NULL AS page_number, 'ocr' AS source, carrier.id AS canonical_id, "
            "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
            "FROM image_pages_words "
            "JOIN image_pages ip ON ip.id = image_pages_words.rowid "
            "JOIN document_index carrier ON carrier.id = ip.document_id "
            "JOIN document_index di ON di.document_id = carrier.document_id "
            "JOIN sources s ON s.id = di.source_id "
            "WHERE image_pages_words MATCH ? "
            "AND di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
            "ORDER BY score DESC, di.file_path",
            (match_expr,),
        ).fetchall()

    _HIGHLIGHT_CHUNK = 500  # SQLite's default cap on bound variables is 999

    @staticmethod
    def get_pdf_term_highlights(
        conn: sqlite3.Connection, match_expr: str, page_ids: list[int]
    ) -> dict[int, str]:
        """Each page's text (by `pdf_pages` id, for those in `page_ids` that match `match_expr`)
        with every match wrapped in 0x02...0x03 - see `search_fulltext_pdf_pages`.

        `match_expr` is a single term (a word, phrase or prefix), so this locates where
        that one term occurs on the pages a `NEAR` query already selected.
        """
        return Document._term_highlights(conn, "pdf_pages_words", match_expr, page_ids)

    @staticmethod
    def get_image_term_highlights(
        conn: sqlite3.Connection, match_expr: str, page_ids: list[int]
    ) -> dict[int, str]:
        """Like `get_pdf_term_highlights`, but for `image_pages`/`image_pages_words`."""
        return Document._term_highlights(conn, "image_pages_words", match_expr, page_ids)

    @staticmethod
    def _term_highlights(
        conn: sqlite3.Connection, table: str, match_expr: str, page_ids: list[int]
    ) -> dict[int, str]:
        highlights: dict[int, str] = {}
        for start in range(0, len(page_ids), Document._HIGHLIGHT_CHUNK):
            chunk = page_ids[start : start + Document._HIGHLIGHT_CHUNK]
            marks = ", ".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT rowid AS page_id, highlight({table}, 0, char(2), char(3)) AS text "
                f"FROM {table} WHERE {table} MATCH ? AND rowid IN ({marks})",
                (match_expr, *chunk),
            ).fetchall()
            highlights.update((row["page_id"], row["text"]) for row in rows)
        return highlights

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
