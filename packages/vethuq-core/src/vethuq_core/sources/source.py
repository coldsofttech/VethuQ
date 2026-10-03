"""Registration of files and folders as VethuQ sources.

A "source" is a file or folder the user has told VethuQ to treat as input for
OCR/indexing. This module only manages the registration (the `sources` table);
the actual scanning/OCR/indexing pipeline consumes it separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vethuq_core.storage import Row, Storage


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
    def _from_row(cls, row: Row) -> Source:
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
    def coerce(path_or_id: str | Path | int) -> str | Path | int:
        """Treat a string of digits as a source id; anything else is left as given.

        This is how the CLI and Python API both read "a source id or a path".
        """
        if isinstance(path_or_id, str) and path_or_id.isdigit():
            return int(path_or_id)
        return path_or_id

    @staticmethod
    def add(storage: Storage, path: str | Path) -> Source:
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
        existing = storage.get_source_by_path(str(resolved))

        if existing is not None:
            if existing["is_active"]:
                raise SourceAlreadyExistsError(f"Path is already registered: {resolved}")
            storage.reactivate_source(existing["id"], source_type, added_at)
            storage.commit()
            row = storage.get_source_by_id(existing["id"])
            assert row is not None
            return Source._from_row(row)

        new_id = storage.insert_source(str(resolved), source_type, added_at)
        storage.commit()

        row = storage.get_source_by_id(new_id)
        assert row is not None
        return Source._from_row(row)

    @staticmethod
    def list_all(storage: Storage, include_inactive: bool = False) -> list[Source]:
        """List registered sources, most recently added first."""
        return [Source._from_row(row) for row in storage.list_source_rows(include_inactive)]

    @staticmethod
    def get(storage: Storage, path_or_id: str | Path | int) -> Source:
        """Look up an active registered source by id or path.

        Raises SourceNotFoundError if no active source matches.
        """
        if isinstance(path_or_id, int):
            row = storage.get_active_source_by_id(path_or_id)
        else:
            resolved = str(Path(path_or_id).expanduser().resolve())
            row = storage.get_active_source_by_path(resolved)

        if row is None:
            raise SourceNotFoundError(f"No active source matches: {path_or_id}")

        return Source._from_row(row)

    @staticmethod
    def progress(storage: Storage, source_id: int) -> tuple[int, int]:
        """`(indexed, total)` count of the files tracked under `source_id`."""
        counts = {
            row["status"]: row["count"] for row in storage.count_document_index_by_status(source_id)
        }
        return counts.get("indexed", 0), sum(counts.values())

    @staticmethod
    def remove(storage: Storage, path_or_id: str | Path | int) -> Source:
        """Soft-delete a registered source by id or path.

        Raises SourceNotFoundError if no active source matches.
        """
        source = Sources.get(storage, path_or_id)
        removed_at = datetime.now(UTC).isoformat()

        storage.soft_delete_source(source.id, removed_at)
        storage.commit()

        updated = storage.get_source_by_id(source.id)
        assert updated is not None
        return Source._from_row(updated)

    @staticmethod
    def promote_surviving_duplicate(
        storage: Storage, document_index_id: int, doomed_ids: set[int]
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
        row = storage.get_document_id_for_index_row(document_index_id)
        if row is None:
            return

        peers = storage.list_document_index_peers(row["document_id"], document_index_id)
        survivors = [peer["id"] for peer in peers if peer["id"] not in doomed_ids]
        if not survivors:
            return

        new_carrier_id = survivors[0]
        storage.reassign_pdf_pages_document(document_index_id, new_carrier_id)
        storage.reassign_image_pages_document(document_index_id, new_carrier_id)

    @staticmethod
    def prune_orphaned_documents(storage: Storage, document_ids: set[int]) -> None:
        """Delete any `documents` row in `document_ids` no `document_index` row references anymore.

        Every `document_index` row is required to carry a `document_id` (its
        logical document), so a `documents` row that's lost its last referencing
        physical row is dead weight rather than data - this is called wherever a
        document_index row's `document_id` changes away from a value or the row
        itself is deleted.
        """
        for document_id in document_ids:
            if not storage.document_index_references_document(document_id):
                storage.delete_document(document_id)

    @staticmethod
    def refresh_document_paths(storage: Storage, document_ids: set[int]) -> None:
        """Point each `documents` row's `file_path` at its earliest non-'removed' copy.

        A logical document can live at several paths (one `document_index` row per
        copy); `documents.file_path` is the primary one. It's NULL when no copy is
        left on disk. Called wherever a document's set of copies, or one copy's
        path or status, changes.
        """
        for document_id in document_ids:
            storage.refresh_document_file_path(document_id)

    @staticmethod
    def purge_expired_sources(storage: Storage, retention_minutes: int | None = None) -> int:
        """Permanently delete removed sources (and their indexed data) past their retention window.

        Returns the number of sources purged.
        """
        from vethuq_core.settings import SourceSettings

        if retention_minutes is None:
            retention_minutes = SourceSettings.get_removed_retention_minutes(storage)

        cutoff = (datetime.now(UTC) - timedelta(minutes=retention_minutes)).isoformat()
        expired = storage.list_expired_removed_sources(cutoff)

        if not expired:
            return 0

        source_ids = [row["id"] for row in expired]
        # `vethuq index run <target>` records whichever of a source's id or path
        # the caller typed into index_runs.target - once the source is gone,
        # either form is a dangling reference, so both are cleared.
        stale_targets = [str(row["id"]) for row in expired] + [row["path"] for row in expired]
        doomed_rows = storage.list_document_index_rows_for_sources(source_ids)
        doomed_ids = {row["id"] for row in doomed_rows}
        doomed_document_ids = {row["document_id"] for row in doomed_rows}
        for document_index_id in doomed_ids:
            Sources.promote_surviving_duplicate(storage, document_index_id, doomed_ids)

        for document_index_id in doomed_ids:
            storage.delete_pdf_pages_for_document(document_index_id)
            storage.delete_image_pages_for_document(document_index_id)
        storage.delete_document_index_for_sources(source_ids)
        storage.delete_sources_by_ids(source_ids)
        Sources.prune_orphaned_documents(storage, doomed_document_ids)
        Sources.refresh_document_paths(storage, doomed_document_ids)

        storage.clear_index_run_targets(stale_targets)

        storage.commit()
        return len(expired)

    @staticmethod
    def purge_expired_documents(storage: Storage, retention_minutes: int | None = None) -> int:
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
            retention_minutes = SourceSettings.get_removed_retention_minutes(storage)

        cutoff = (datetime.now(UTC) - timedelta(minutes=retention_minutes)).isoformat()
        expired = storage.list_expired_removed_document_index_rows(cutoff)

        if not expired:
            return 0

        doomed_ids = {row["id"] for row in expired}
        doomed_document_ids = {
            row["document_id"] for row in storage.list_document_index_rows_by_ids(list(doomed_ids))
        }
        for document_index_id in doomed_ids:
            Sources.promote_surviving_duplicate(storage, document_index_id, doomed_ids)

        for document_index_id in doomed_ids:
            storage.delete_pdf_pages_for_document(document_index_id)
            storage.delete_image_pages_for_document(document_index_id)
        storage.delete_document_index_by_ids(list(doomed_ids))
        Sources.prune_orphaned_documents(storage, doomed_document_ids)
        Sources.refresh_document_paths(storage, doomed_document_ids)

        storage.commit()
        return len(doomed_ids)
