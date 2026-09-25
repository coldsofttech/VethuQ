"""Registration of files and folders as VethuQ sources.

A "source" is a file or folder the user has told VethuQ to treat as input for
OCR/indexing. This module only manages the registration (the `sources` table);
the actual scanning/OCR/indexing pipeline consumes it separately.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
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
        )


def add_source(conn: sqlite3.Connection, path: str | Path) -> Source:
    """Register a file or folder as a source. Folders are indexed recursively.

    Raises SourcePathError if the path does not exist or is neither a file nor
    a folder, and SourceAlreadyExistsError if it is already registered.
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
    try:
        cursor = conn.execute(
            """
            INSERT INTO sources (path, source_type, status, added_at, is_active)
            VALUES (?, ?, 'pending', ?, 1)
            """,
            (str(resolved), source_type, added_at),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SourceAlreadyExistsError(f"Path is already registered: {resolved}") from exc

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


def remove_source(conn: sqlite3.Connection, path_or_id: str | Path | int) -> Source:
    """Soft-delete a registered source by id or path.

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

    conn.execute(
        "UPDATE sources SET is_active = 0, status = 'removed' WHERE id = ?",
        (row["id"],),
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM sources WHERE id = ?", (row["id"],)).fetchone()
    return Source._from_row(updated)
