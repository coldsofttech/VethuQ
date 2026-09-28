"""SQL for the `documents`, `document_index`, `pdf_pages`, and `image_pages` tables."""

from __future__ import annotations

import sqlite3


def get_document_id_for_index_row(
    conn: sqlite3.Connection, document_index_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT document_id FROM document_index WHERE id = ?", (document_index_id,)
    ).fetchone()


def list_document_index_peers(
    conn: sqlite3.Connection, document_id: int, exclude_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id FROM document_index WHERE document_id = ? AND id != ? ORDER BY id ASC",
        (document_id, exclude_id),
    ).fetchall()


def reassign_pdf_pages_document(
    conn: sqlite3.Connection, old_document_index_id: int, new_document_index_id: int
) -> None:
    conn.execute(
        "UPDATE pdf_pages SET document_id = ? WHERE document_id = ?",
        (new_document_index_id, old_document_index_id),
    )


def reassign_image_pages_document(
    conn: sqlite3.Connection, old_document_index_id: int, new_document_index_id: int
) -> None:
    conn.execute(
        "UPDATE image_pages SET document_id = ? WHERE document_id = ?",
        (new_document_index_id, old_document_index_id),
    )


def document_index_references_document(conn: sqlite3.Connection, document_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM document_index WHERE document_id = ? LIMIT 1", (document_id,)
    ).fetchone()
    return row is not None


def delete_document(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))


def insert_document(conn: sqlite3.Connection, created_at: str) -> int:
    cursor = conn.execute("INSERT INTO documents (created_at) VALUES (?)", (created_at,))
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def list_document_index_rows_for_sources(
    conn: sqlite3.Connection, source_ids: list[int]
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(source_ids))
    return conn.execute(
        f"SELECT id, document_id FROM document_index WHERE source_id IN ({placeholders})",
        source_ids,
    ).fetchall()


def delete_pdf_pages_for_document(conn: sqlite3.Connection, document_index_id: int) -> None:
    conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_index_id,))


def delete_image_pages_for_document(conn: sqlite3.Connection, document_index_id: int) -> None:
    conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_index_id,))


def delete_document_index_for_sources(conn: sqlite3.Connection, source_ids: list[int]) -> None:
    placeholders = ",".join("?" * len(source_ids))
    conn.execute(f"DELETE FROM document_index WHERE source_id IN ({placeholders})", source_ids)


def list_expired_removed_document_index_rows(
    conn: sqlite3.Connection, cutoff: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id FROM document_index "
        "WHERE status = 'removed' AND removed_at IS NOT NULL AND removed_at <= ?",
        (cutoff,),
    ).fetchall()


def list_document_index_rows_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(ids))
    return conn.execute(
        f"SELECT document_id FROM document_index WHERE id IN ({placeholders})", ids
    ).fetchall()


def delete_document_index_by_ids(conn: sqlite3.Connection, ids: list[int]) -> None:
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM document_index WHERE id IN ({placeholders})", ids)


def find_duplicate_document_index(
    conn: sqlite3.Connection, sha256: str, exclude_id: int
) -> sqlite3.Row | None:
    """Return the earliest-indexed `document_index` row (id, document_id) matching `sha256`."""
    return conn.execute(
        "SELECT id, document_id FROM document_index "
        "WHERE sha256 = ? AND id != ? AND status = 'indexed' ORDER BY id ASC LIMIT 1",
        (sha256, exclude_id),
    ).fetchone()


def get_document_index_by_path(conn: sqlite3.Connection, file_path: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, document_id, sha256 FROM document_index WHERE file_path = ?",
        (file_path,),
    ).fetchone()


def get_document_index_id_by_path(conn: sqlite3.Connection, file_path: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id FROM document_index WHERE file_path = ?", (file_path,)
    ).fetchone()


def upsert_document_index(
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
) -> None:
    conn.execute(
        """
        INSERT INTO document_index
            (source_id, document_id, file_path, file_type, status, started_at,
             file_size_bytes, sha256, mtime, created_at, modified_at)
        VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            document_id = excluded.document_id,
            status = 'pending', error_message = NULL, indexed_at = NULL,
            started_at = excluded.started_at, completed_at = NULL,
            file_size_bytes = excluded.file_size_bytes, sha256 = excluded.sha256,
            mtime = excluded.mtime, created_at = excluded.created_at,
            modified_at = excluded.modified_at
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


def list_tracked_document_index_rows(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, file_path, sha256 FROM document_index "
        "WHERE source_id = ? AND status != 'removed'",
        (source_id,),
    ).fetchall()


def update_document_index_path(
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


def mark_document_index_removed(conn: sqlite3.Connection, row_id: int, removed_at: str) -> None:
    conn.execute(
        "UPDATE document_index SET status = 'removed', removed_at = ? WHERE id = ?",
        (removed_at, row_id),
    )


def mark_document_index_indexed(conn: sqlite3.Connection, document_id: int, now: str) -> None:
    conn.execute(
        "UPDATE document_index SET status = 'indexed', indexed_at = ?, completed_at = ? "
        "WHERE id = ?",
        (now, now, document_id),
    )


def mark_document_index_error(
    conn: sqlite3.Connection, document_id: int, message: str, now: str
) -> None:
    conn.execute(
        "UPDATE document_index SET status = 'error', error_message = ?, completed_at = ? "
        "WHERE id = ?",
        (message, now, document_id),
    )


def get_document_index_metrics_stats(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT started_at, completed_at, peak_memory_mb, cpu_percent, file_size_bytes "
        "FROM document_index WHERE id = ?",
        (document_id,),
    ).fetchone()
    assert row is not None
    return row


def get_page_confidences(
    conn: sqlite3.Connection, file_type: str, document_id: int
) -> list[sqlite3.Row]:
    table = "pdf_pages" if file_type == "pdf" else "image_pages"
    return conn.execute(
        f"SELECT confidence FROM {table} WHERE document_id = ?", (document_id,)
    ).fetchall()


def get_pdf_page_sources(conn: sqlite3.Connection, document_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT confidence, source FROM pdf_pages WHERE document_id = ?", (document_id,)
    ).fetchall()


def get_document_index_pending_check(
    conn: sqlite3.Connection, file_path: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT status, mtime, file_size_bytes, sha256 FROM document_index WHERE file_path = ?",
        (file_path,),
    ).fetchone()


def update_document_index_retry_stats(
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


def insert_pdf_pages(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        "INSERT INTO pdf_pages "
        "(document_id, page_number, ocr_text, confidence, source, "
        "ocr_engine, language, image_width, image_height) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def insert_image_page(
    conn: sqlite3.Connection,
    document_id: int,
    ocr_text: str,
    confidence: float,
    ocr_engine: str | None,
    language: str | None,
    image_width: int | None,
    image_height: int | None,
) -> None:
    conn.execute(
        "INSERT INTO image_pages "
        "(document_id, ocr_text, confidence, ocr_engine, language, "
        "image_width, image_height) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (document_id, ocr_text, confidence, ocr_engine, language, image_width, image_height),
    )


def get_document_result_rows(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
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


def list_indexed_pdf_pages(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT di.id AS document_id, di.file_path AS file_path, pp.ocr_text AS ocr_text, "
        "pp.page_number AS page_number, carrier.id AS canonical_id, "
        "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
        "FROM document_index di "
        "JOIN sources s ON s.id = di.source_id "
        "JOIN document_index carrier ON carrier.document_id = di.document_id "
        "JOIN pdf_pages pp ON pp.document_id = carrier.id "
        "WHERE di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'pdf' "
        "ORDER BY di.file_path, pp.page_number"
    ).fetchall()


def list_indexed_image_pages(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT di.id AS document_id, di.file_path AS file_path, ip.ocr_text AS ocr_text, "
        "NULL AS page_number, carrier.id AS canonical_id, "
        "CASE WHEN carrier.id != di.id THEN carrier.file_path END AS duplicate_of_path "
        "FROM document_index di "
        "JOIN sources s ON s.id = di.source_id "
        "JOIN document_index carrier ON carrier.document_id = di.document_id "
        "JOIN image_pages ip ON ip.document_id = carrier.id "
        "WHERE di.status = 'indexed' AND s.is_active = 1 AND di.file_type = 'image' "
        "ORDER BY di.file_path"
    ).fetchall()


def get_pdf_page_counts_by_document(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT document_id, COUNT(*) AS total FROM pdf_pages GROUP BY document_id"
    ).fetchall()
