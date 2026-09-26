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
        "SELECT id FROM sources "
        "WHERE status = 'removed' AND removed_at IS NOT NULL AND removed_at <= ?",
        (cutoff,),
    ).fetchall()

    for row in expired:
        source_id = row["id"]
        document_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM document_index WHERE source_id = ?", (source_id,)
            ).fetchall()
        ]
        for document_id in document_ids:
            conn.execute("DELETE FROM pdf_pages WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM image_pages WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM document_index WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    if expired:
        conn.commit()

    return len(expired)
