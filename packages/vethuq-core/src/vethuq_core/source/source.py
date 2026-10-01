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

from vethuq_core.db.queries import Document
from vethuq_core.db.queries.sources import Source as SourceQuery


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


class Sources:
    @staticmethod
    def add(conn: sqlite3.Connection, path: str | Path) -> Source:
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
        existing = SourceQuery.get_by_path(conn, str(resolved))

        if existing is not None:
            if existing["is_active"]:
                raise SourceAlreadyExistsError(f"Path is already registered: {resolved}")
            SourceQuery.reactivate(conn, existing["id"], source_type, added_at)
            conn.commit()
            row = SourceQuery.get_by_id(conn, existing["id"])
            assert row is not None
            return Source._from_row(row)

        new_id = SourceQuery.insert(conn, str(resolved), source_type, added_at)
        conn.commit()

        row = SourceQuery.get_by_id(conn, new_id)
        assert row is not None
        return Source._from_row(row)

    @staticmethod
    def list_all(conn: sqlite3.Connection, include_inactive: bool = False) -> list[Source]:
        """List registered sources, most recently added first."""
        return [Source._from_row(row) for row in SourceQuery.list_rows(conn, include_inactive)]

    @staticmethod
    def get(conn: sqlite3.Connection, path_or_id: str | Path | int) -> Source:
        """Look up an active registered source by id or path.

        Raises SourceNotFoundError if no active source matches.
        """
        if isinstance(path_or_id, int):
            row = SourceQuery.get_active_by_id(conn, path_or_id)
        else:
            resolved = str(Path(path_or_id).expanduser().resolve())
            row = SourceQuery.get_active_by_path(conn, resolved)

        if row is None:
            raise SourceNotFoundError(f"No active source matches: {path_or_id}")

        return Source._from_row(row)

    @staticmethod
    def remove(conn: sqlite3.Connection, path_or_id: str | Path | int) -> Source:
        """Soft-delete a registered source by id or path.

        Raises SourceNotFoundError if no active source matches.
        """
        source = Sources.get(conn, path_or_id)
        removed_at = datetime.now(UTC).isoformat()

        SourceQuery.soft_delete(conn, source.id, removed_at)
        conn.commit()

        updated = SourceQuery.get_by_id(conn, source.id)
        assert updated is not None
        return Source._from_row(updated)

    @staticmethod
    def promote_surviving_duplicate(
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
        row = Document.get_id_for_index_row(conn, document_index_id)
        if row is None:
            return

        peers = Document.list_index_peers(conn, row["document_id"], document_index_id)
        survivors = [peer["id"] for peer in peers if peer["id"] not in doomed_ids]
        if not survivors:
            return

        new_carrier_id = survivors[0]
        Document.reassign_pdf_pages(conn, document_index_id, new_carrier_id)
        Document.reassign_image_pages(conn, document_index_id, new_carrier_id)

    @staticmethod
    def prune_orphaned_documents(conn: sqlite3.Connection, document_ids: set[int]) -> None:
        """Delete any `documents` row in `document_ids` no `document_index` row references anymore.

        Every `document_index` row is required to carry a `document_id` (its
        logical document), so a `documents` row that's lost its last referencing
        physical row is dead weight rather than data - this is called wherever a
        document_index row's `document_id` changes away from a value or the row
        itself is deleted.
        """
        for document_id in document_ids:
            if not Document.index_references_document(conn, document_id):
                Document.delete(conn, document_id)

    @staticmethod
    def refresh_document_paths(conn: sqlite3.Connection, document_ids: set[int]) -> None:
        """Point each `documents` row's `file_path` at its earliest non-'removed' copy.

        A logical document can live at several paths (one `document_index` row per
        copy); `documents.file_path` is the primary one. It's NULL when no copy is
        left on disk. Called wherever a document's set of copies, or one copy's
        path or status, changes.
        """
        for document_id in document_ids:
            Document.refresh_file_path(conn, document_id)

    @staticmethod
    def purge_expired_sources(
        conn: sqlite3.Connection, retention_minutes: int | None = None
    ) -> int:
        """Permanently delete removed sources (and their indexed data) past their retention window.

        Returns the number of sources purged.
        """
        from vethuq_core.settings import SourceSettings

        if retention_minutes is None:
            retention_minutes = SourceSettings.get_removed_retention_minutes(conn)

        cutoff = (datetime.now(UTC) - timedelta(minutes=retention_minutes)).isoformat()
        expired = SourceQuery.list_expired_removed(conn, cutoff)

        if not expired:
            return 0

        source_ids = [row["id"] for row in expired]
        # `vethuq index run <target>` records whichever of a source's id or path
        # the caller typed into index_runs.target - once the source is gone,
        # either form is a dangling reference, so both are cleared.
        stale_targets = [str(row["id"]) for row in expired] + [row["path"] for row in expired]
        doomed_rows = Document.list_index_rows_for_sources(conn, source_ids)
        doomed_ids = {row["id"] for row in doomed_rows}
        doomed_document_ids = {row["document_id"] for row in doomed_rows}
        for document_index_id in doomed_ids:
            Sources.promote_surviving_duplicate(conn, document_index_id, doomed_ids)

        for document_index_id in doomed_ids:
            Document.delete_pdf_pages(conn, document_index_id)
            Document.delete_image_pages(conn, document_index_id)
        Document.delete_index_for_sources(conn, source_ids)
        SourceQuery.delete_by_ids(conn, source_ids)
        Sources.prune_orphaned_documents(conn, doomed_document_ids)
        Sources.refresh_document_paths(conn, doomed_document_ids)

        SourceQuery.clear_index_run_targets(conn, stale_targets)

        conn.commit()
        return len(expired)

    @staticmethod
    def purge_expired_documents(
        conn: sqlite3.Connection, retention_minutes: int | None = None
    ) -> int:
        """Permanently delete individual documents marked 'removed' past their retention window.

        A document is marked 'removed' (rather than deleted outright) when its
        file goes missing from an otherwise still-active source - see
        `vethuq_core.ocr.Document.reconcile_renamed_and_removed` - so it survives
        briefly in case the file reappears (e.g. it was moved out and back, or
        the miss was transient). This mirrors `Sources.purge_expired_sources`
        but at the individual-file level, and shares the same retention setting.

        Returns the number of documents purged.
        """
        from vethuq_core.settings import SourceSettings

        if retention_minutes is None:
            retention_minutes = SourceSettings.get_removed_retention_minutes(conn)

        cutoff = (datetime.now(UTC) - timedelta(minutes=retention_minutes)).isoformat()
        expired = Document.list_expired_removed_index_rows(conn, cutoff)

        if not expired:
            return 0

        doomed_ids = {row["id"] for row in expired}
        doomed_document_ids = {
            row["document_id"] for row in Document.list_index_rows_by_ids(conn, list(doomed_ids))
        }
        for document_index_id in doomed_ids:
            Sources.promote_surviving_duplicate(conn, document_index_id, doomed_ids)

        for document_index_id in doomed_ids:
            Document.delete_pdf_pages(conn, document_index_id)
            Document.delete_image_pages(conn, document_index_id)
        Document.delete_index_by_ids(conn, list(doomed_ids))
        Sources.prune_orphaned_documents(conn, doomed_document_ids)
        Sources.refresh_document_paths(conn, doomed_document_ids)

        conn.commit()
        return len(doomed_ids)
