"""Registration of files and folders as VethuQ sources.

A "source" is a file or folder the user has told VethuQ to treat as input for
OCR/indexing. This module only manages the registration (the `sources` table);
the actual scanning/OCR/indexing pipeline consumes it separately.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


class SourceError(Exception):
    """Base class for source-registration errors."""


class SourcePathError(SourceError):
    """The given path does not exist or is not a file/folder VethuQ can index."""


class SourceAlreadyExistsError(SourceError):
    """The given path is already registered as a source."""


class SourceNotFoundError(SourceError):
    """No registered source matches the given id or path."""


@dataclass(frozen=True)
class Source:
    id: int
    path: str
    source_type: str  # "file" | "folder"
    status: str
    added_at: str
    last_scanned_at: str | None
    is_active: bool
    removed_at: str | None

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> Source:
        return cls(
            id=row["id"],
            path=row["path"],
            source_type=row["source_type"],
            status=row["status"],
            added_at=row["added_at"],
            last_scanned_at=row["last_scanned_at"],
            is_active=bool(row["is_active"]),
            removed_at=row["removed_at"],
        )


def add_source(conn: sqlite3.Connection, path: str | Path) -> Source:
    """Register a file or folder as a source. Folders are indexed recursively.

    Re-adding a path that was previously removed reactivates that source
    (reset to 'pending') rather than failing.

    Raises SourcePathError if the path does not exist or is neither a file nor
    a folder, and SourceAlreadyExistsError if it is already an active source.
    """
    resolved = Path(path).expanduser().resolve()

    if not resolved.exists():
        raise SourcePathError(f"Path does not exist: {resolved}")
    if resolved.is_dir():
        source_type = "folder"
    elif resolved.is_file():
        source_type = "file"
    else:
        raise SourcePathError(f"Path is neither a file nor a folder: {resolved}")

    added_at = datetime.now(UTC).isoformat()
    existing = conn.execute("SELECT * FROM sources WHERE path = ?", (str(resolved),)).fetchone()

    if existing is not None:
        if existing["is_active"]:
            raise SourceAlreadyExistsError(f"Path is already registered: {resolved}")
        conn.execute(
            """
            UPDATE sources
            SET source_type = ?, status = 'pending', added_at = ?,
                last_scanned_at = NULL, is_active = 1, removed_at = NULL
            WHERE id = ?
            """,
            (source_type, added_at, existing["id"]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (existing["id"],)).fetchone()
        return Source._from_row(row)

    cursor = conn.execute(
        """
        INSERT INTO sources (path, source_type, status, added_at, is_active)
        VALUES (?, ?, 'pending', ?, 1)
        """,
        (str(resolved), source_type, added_at),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM sources WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return Source._from_row(row)


def list_sources(conn: sqlite3.Connection, include_inactive: bool = False) -> list[Source]:
    """List registered sources, most recently added first."""
    query = "SELECT * FROM sources"
    if not include_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY added_at DESC"
    rows = conn.execute(query).fetchall()
    return [Source._from_row(row) for row in rows]


def get_source(conn: sqlite3.Connection, path_or_id: str | Path | int) -> Source:
    """Look up an active registered source by id or path.

    Raises SourceNotFoundError if no active source matches.
    """
    if isinstance(path_or_id, int):
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ? AND is_active = 1", (path_or_id,)
        ).fetchone()
    else:
        resolved = str(Path(path_or_id).expanduser().resolve())
        row = conn.execute(
            "SELECT * FROM sources WHERE path = ? AND is_active = 1", (resolved,)
        ).fetchone()

    if row is None:
        raise SourceNotFoundError(f"No active source matches: {path_or_id}")

    return Source._from_row(row)


def remove_source(conn: sqlite3.Connection, path_or_id: str | Path | int) -> Source:
    """Soft-delete a registered source by id or path.

    Raises SourceNotFoundError if no active source matches.
    """
    source = get_source(conn, path_or_id)
    removed_at = datetime.now(UTC).isoformat()

    conn.execute(
        "UPDATE sources SET is_active = 0, status = 'removed', removed_at = ? WHERE id = ?",
        (removed_at, source.id),
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM sources WHERE id = ?", (source.id,)).fetchone()
    return Source._from_row(updated)


def _promote_surviving_duplicate(
    conn: sqlite3.Connection, document_index_id: int, doomed_ids: set[int]
) -> None:
    """Before `document_index_id`'s content moves on, hand off its OCR pages if it holds any.

    Every `document_index` row sharing `document_index_id`'s `document_id` is
    content-identical to it (they're the same logical document). If it's the
    one currently holding the OCR pages for that document and at least one
    peer isn't also about to be deleted (`doomed_ids`), the earliest-id
    survivor takes over those pages (re-keyed to its own id) so the logical
    document keeps reflecting content that's still on disk. If every peer is
    doomed too, or `document_index_id` never held any pages of its own (it
    was already just a checksum link), there's nothing to hand off.
    """
    row = conn.execute(
        "SELECT document_id FROM document_index WHERE id = ?", (document_index_id,)
    ).fetchone()
    if row is None:
        return

    peers = conn.execute(
        "SELECT id FROM document_index WHERE document_id = ? AND id != ? ORDER BY id ASC",
        (row["document_id"], document_index_id),
    ).fetchall()
    survivors = [peer["id"] for peer in peers if peer["id"] not in doomed_ids]
    if not survivors:
        return

    new_carrier_id = survivors[0]
    conn.execute(
        "UPDATE pdf_pages SET document_id = ? WHERE document_id = ?",
        (new_carrier_id, document_index_id),
    )
    conn.execute(
        "UPDATE image_pages SET document_id = ? WHERE document_id = ?",
        (new_carrier_id, document_index_id),
    )


def _prune_orphaned_documents(conn: sqlite3.Connection, document_ids: set[int]) -> None:
    """Delete any `documents` row in `document_ids` no `document_index` row references anymore.

    Every `document_index` row is required to carry a `document_id` (its
    logical document), so a `documents` row that's lost its last referencing
    physical row is dead weight rather than data - this is called wherever a
    document_index row's `document_id` changes away from a value or the row
    itself is deleted.
    """
    for document_id in document_ids:
        still_referenced = conn.execute(
            "SELECT 1 FROM document_index WHERE document_id = ? LIMIT 1", (document_id,)
        ).fetchone()
        if still_referenced is None:
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))


def _refresh_document_paths(conn: sqlite3.Connection, document_ids: set[int]) -> None:
    """Point each `documents` row's `file_path` at its earliest non-'removed' copy.

    A logical document can live at several paths (one `document_index` row per
    copy); `documents.file_path` is the primary one. It's NULL when no copy is
    left on disk. Called wherever a document's set of copies, or one copy's
    path or status, changes.
    """
    for document_id in document_ids:
        conn.execute(
            "UPDATE documents SET file_path = ("
            "SELECT file_path FROM document_index "
            "WHERE document_id = documents.id AND status != 'removed' "
            "ORDER BY id ASC LIMIT 1) WHERE id = ?",
            (document_id,),
        )


def purge_expired_removed_sources(
    conn: sqlite3.Connection, retention_minutes: int | None = None
) -> int:
    """Permanently delete removed sources (and their indexed data) past their retention window.

    Returns the number of sources purged.
    """
    from vethuq_core.settings import get_removed_source_retention_minutes

    if retention_minutes is None:
        retention_minutes = get_removed_source_retention_minutes(conn)

    cutoff = (datetime.now(UTC) - timedelta(minutes=retention_minutes)).isoformat()
    expired = conn.execute(
        "SELECT id, path FROM sources "
        "WHERE status = 'removed' AND removed_at IS NOT NULL AND removed_at <= ?",
        (cutoff,),
    ).fetchall()

    if not expired:
        return 0

    source_ids = [row["id"] for row in expired]
    placeholders = ",".join("?" * len(source_ids))
    # `vethuq index run <target>` records whichever of a source's id or path
    # the caller typed into index_runs.target - once the source is gone,
    # either form is a dangling reference, so both are cleared.
    stale_targets = [str(row["id"]) for row in expired] + [row["path"] for row in expired]
    doomed_rows = conn.execute(
        f"SELECT id, document_id FROM document_index WHERE source_id IN ({placeholders})",
        source_ids,
    ).fetchall()
    doomed_ids = {row["id"] for row in doomed_rows}
    doomed_document_ids = {row["document_id"] for row in doomed_rows}
    for document_index_id in doomed_ids:
        _promote_surviving_duplicate(conn, document_index_id, doomed_ids)

    for document_index_id in doomed_ids:
        conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_index_id,))
        conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_index_id,))
    conn.execute(f"DELETE FROM document_index WHERE source_id IN ({placeholders})", source_ids)
    conn.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", source_ids)
    _prune_orphaned_documents(conn, doomed_document_ids)
    _refresh_document_paths(conn, doomed_document_ids)

    target_placeholders = ",".join("?" * len(stale_targets))
    conn.execute(
        f"UPDATE index_runs SET target = NULL WHERE target IN ({target_placeholders})",
        stale_targets,
    )

    conn.commit()
    return len(expired)


def purge_expired_removed_documents(
    conn: sqlite3.Connection, retention_minutes: int | None = None
) -> int:
    """Permanently delete individual documents marked 'removed' past their retention window.

    A document is marked 'removed' (rather than deleted outright) when its
    file goes missing from an otherwise still-active source - see
    `vethuq_core.ocr._reconcile_renamed_and_removed_files` - so it survives
    briefly in case the file reappears (e.g. it was moved out and back, or
    the miss was transient). This mirrors `purge_expired_removed_sources`
    but at the individual-file level, and shares the same retention setting.

    Returns the number of documents purged.
    """
    from vethuq_core.settings import get_removed_source_retention_minutes

    if retention_minutes is None:
        retention_minutes = get_removed_source_retention_minutes(conn)

    cutoff = (datetime.now(UTC) - timedelta(minutes=retention_minutes)).isoformat()
    expired = conn.execute(
        "SELECT id FROM document_index "
        "WHERE status = 'removed' AND removed_at IS NOT NULL AND removed_at <= ?",
        (cutoff,),
    ).fetchall()

    if not expired:
        return 0

    doomed_ids = {row["id"] for row in expired}
    placeholders = ",".join("?" * len(doomed_ids))
    doomed_document_ids = {
        row["document_id"]
        for row in conn.execute(
            f"SELECT document_id FROM document_index WHERE id IN ({placeholders})",
            list(doomed_ids),
        ).fetchall()
    }
    for document_index_id in doomed_ids:
        _promote_surviving_duplicate(conn, document_index_id, doomed_ids)

    for document_index_id in doomed_ids:
        conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_index_id,))
        conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_index_id,))
    conn.execute(f"DELETE FROM document_index WHERE id IN ({placeholders})", list(doomed_ids))
    _prune_orphaned_documents(conn, doomed_document_ids)
    _refresh_document_paths(conn, doomed_document_ids)

    conn.commit()
    return len(doomed_ids)
