"""Registration of files and folders as VethuQ sources.

A "source" is a file or folder the user has told VethuQ to treat as input for
OCR/indexing. This module only manages the registration (the `sources` table);
the actual scanning/OCR/indexing pipeline consumes it separately.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vethuq_core.logs import Logs
from vethuq_core.storage import Row, Storage


class SourceError(Exception):
    """Base class for source-registration errors."""


class SourcePathError(SourceError):
    """The given path does not exist or is not a file/folder VethuQ can index."""


class SourceAlreadyExistsError(SourceError):
    """The given path is already registered as a source."""


class SourceNotFoundError(SourceError):
    """No registered source matches the given id or path."""


class SourceNotRemovedError(SourceError):
    """The source or file is still active, so it can't be purged."""


@dataclass(frozen=True)
class PurgeResult:
    kind: str  # "file" | "folder" for a source, or "file" for a single removed file
    path: str


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
    # Comma-separated language ids this source is read in (`en,te`, or `auto`); None means the
    # global `ocr_languages` setting applies.
    languages: str | None = None

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
            languages=row["languages"] if "languages" in row.keys() else None,  # noqa: SIM118
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "id": self.id,
            "path": self.path,
            "type": self.source_type,
            "status": self.status,
            "added_at": self.added_at,
            "last_scanned_at": self.last_scanned_at,
        }
        if self.languages:
            data["languages"] = self.languages
        return data


@dataclass(frozen=True)
class PhaseTiming:
    """Timing of one deeper OCR phase (2+) of a document."""

    phase: int
    started_at: str
    completed_at: str | None
    duration_seconds: float


@dataclass(frozen=True)
class SourceFile:
    """One file tracked under a source, as listed by `vethuq source list <source>`."""

    id: int
    file_path: str
    file_type: str  # "pdf" | "image"
    status: str
    error_message: str | None
    file_size_bytes: int | None
    started_at: str | None
    completed_at: str | None
    indexed_at: str | None
    duration: float | None
    retry_count: int
    confidence: float | None
    duplicate_of_path: str | None
    pages: int
    ocr_phase: int | None  # highest phase every page has completed; None if no pages yet
    ocr_angles: list[int]
    phase_timings: list[PhaseTiming]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "file": self.file_path,
            "file_type": self.file_type,
            "status": self.status,
            "error": self.error_message,
            "size_bytes": self.file_size_bytes,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "indexed_at": self.indexed_at,
            "duration": self.duration,
            "retry_count": self.retry_count,
            "confidence": self.confidence,
            "duplicate_of": self.duplicate_of_path,
            "pages": self.pages,
            "ocr_phase": self.ocr_phase,
            "ocr_angles": self.ocr_angles,
            "phases": [
                {
                    "phase": t.phase,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                    "duration": t.duration_seconds,
                }
                for t in self.phase_timings
            ],
        }


class Sources:
    _logger = Logs.get_logger("database")

    @staticmethod
    def coerce(path_or_id: str | Path | int) -> str | Path | int:
        """Treat a string of digits as a source id; anything else is left as given.

        This is how the CLI and Python API both read "a source id or a path".
        """
        if isinstance(path_or_id, str) and path_or_id.isdigit():
            return int(path_or_id)
        return path_or_id

    @staticmethod
    def _languages_value(languages: str | Sequence[str] | None) -> str | None:
        """The stored form of a language choice (`en,te`), validated; None for no choice."""
        from vethuq_core.languages import LanguageSelection

        ids = LanguageSelection.parse(languages)
        return LanguageSelection.format(ids) if ids else None

    @staticmethod
    def set_languages(
        storage: Storage, path_or_id: str | Path | int, languages: str | Sequence[str] | None
    ) -> Source:
        """Choose the OCR languages `path_or_id`'s files are read in (None: back to the setting).

        Takes effect for files indexed from now on; already indexed files keep what they have
        until re-indexed (`vethuq index reindex`). Raises `UnknownLanguageError` for an unknown
        language id and `SourceNotFoundError` if no active source matches.
        """
        value = Sources._languages_value(languages)
        source = Sources.get(storage, path_or_id)
        storage.set_source_languages(source.id, value)
        storage.commit()
        return Sources.get(storage, source.id)

    @staticmethod
    def add(
        storage: Storage, path: str | Path, languages: str | Sequence[str] | None = None
    ) -> Source:
        """Register a file or folder as a source. Folders are indexed recursively.

        `languages` names the OCR languages the source is read in (`"te"`, `"en,te"`, `"auto"`);
        left out, the global `ocr_languages` setting applies.

        Re-adding a path that was previously removed reactivates that source
        (reset to 'pending') rather than failing.

        Raises SourcePathError if the path does not exist or is neither a file nor
        a folder, and SourceAlreadyExistsError if it is already an active source.
        """
        language_value = Sources._languages_value(languages)
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
            if language_value is not None:
                storage.set_source_languages(existing["id"], language_value)
            storage.commit()
            row = storage.get_source_by_id(existing["id"])
            assert row is not None
            return Source._from_row(row)

        new_id = storage.insert_source(str(resolved), source_type, added_at)
        if language_value is not None:
            storage.set_source_languages(new_id, language_value)
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
    def list_files(storage: Storage, path_or_id: str | Path | int) -> list[SourceFile]:
        """List every file tracked under an active source, ordered by path.

        Duplicates have no pages of their own, so their confidence and OCR phase
        are the original's. Raises SourceNotFoundError if no active source matches.
        """
        source = Sources.get(storage, path_or_id)
        files = []
        for row in storage.list_source_file_rows(source.id):
            pages = storage.list_page_ocr_state(row["file_type"], row["canonical_id"])
            angles: set[int] = set()
            for page in pages:
                angles.update(int(a) for a in page["ocr_angles"].split(",") if a.strip())
            confidence = None
            if row["status"] == "indexed" and pages:
                confidence = sum(p["confidence"] for p in pages) / len(pages)

            duration = None
            if row["started_at"] and row["completed_at"]:
                duration = (
                    datetime.fromisoformat(row["completed_at"])
                    - datetime.fromisoformat(row["started_at"])
                ).total_seconds()

            files.append(
                SourceFile(
                    id=row["id"],
                    file_path=row["file_path"],
                    file_type=row["file_type"],
                    status=row["status"],
                    error_message=row["error_message"],
                    file_size_bytes=row["file_size_bytes"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    indexed_at=row["indexed_at"],
                    duration=duration,
                    retry_count=row["retry_count"],
                    confidence=confidence,
                    duplicate_of_path=row["duplicate_of_path"],
                    pages=len(pages),
                    ocr_phase=min((p["ocr_phase"] for p in pages), default=None),
                    ocr_angles=sorted(angles),
                    phase_timings=[
                        PhaseTiming(
                            phase=t["phase"],
                            started_at=t["started_at"],
                            completed_at=t["completed_at"],
                            duration_seconds=t["duration_seconds"],
                        )
                        for t in storage.list_phase_rows(row["document_id"])
                    ],
                )
            )
        return files

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

        Sources._delete_sources(storage, expired, trigger="retention")
        return len(expired)

    @staticmethod
    def _delete_sources(storage: Storage, rows: Sequence[Row], trigger: str) -> None:
        """Permanently delete the given `sources` rows with their indexed data, then commit.

        `trigger` ('manual' or 'retention') is only recorded in the database log.
        """
        source_ids = [row["id"] for row in rows]
        # `vethuq index run <target>` records whichever of a source's id or path
        # the caller typed into index_runs.target - once the source is gone,
        # either form is a dangling reference, so both are cleared.
        stale_targets = [str(row["id"]) for row in rows] + [row["path"] for row in rows]
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
        for row in rows:
            Sources._logger.info(
                "Cleanup (%s): purged source id=%d path=%s (%d indexed file record(s) in total)",
                trigger,
                row["id"],
                row["path"],
                len(doomed_ids),
            )

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

        Sources._delete_document_rows(storage, {row["id"] for row in expired}, trigger="retention")
        return len(expired)

    @staticmethod
    def _delete_document_rows(
        storage: Storage, doomed_ids: set[int], trigger: str, path: str | None = None
    ) -> None:
        """Permanently delete the given `document_index` rows with their pages, then commit.

        `trigger` ('manual' or 'retention') and `path` (when it's a single known file) are
        only recorded in the database log.
        """
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
        Sources._logger.info(
            "Cleanup (%s): purged %d removed file record(s)%s",
            trigger,
            len(doomed_ids),
            f" path={path}" if path else "",
        )

    @staticmethod
    def _find_purgeable(
        storage: Storage, path_or_id: str | Path | int
    ) -> tuple[PurgeResult, Row | None, int | None]:
        """Resolve a purge target to `(result, source_row, document_index_id)`; one id is set."""
        if isinstance(path_or_id, int):
            source_row = storage.get_source_by_id(path_or_id)
        else:
            resolved = str(Path(path_or_id).expanduser().resolve())
            source_row = storage.get_source_by_path(resolved)

        if source_row is not None:
            source = Source._from_row(source_row)
            if source.is_active:
                raise SourceNotRemovedError(
                    f"Source is still active: {source.path} - remove it before purging."
                )
            return PurgeResult(kind=source.source_type, path=source.path), source_row, None

        if not isinstance(path_or_id, int):
            file_row = storage.get_document_index_by_path(resolved)
            if file_row is not None:
                if file_row["status"] != "removed":
                    raise SourceNotRemovedError(
                        f"File is not removed: {resolved} - only removed files can be purged."
                    )
                return PurgeResult(kind="file", path=resolved), None, file_row["id"]

        raise SourceNotFoundError(f"No source or file matches: {path_or_id}")

    @staticmethod
    def check_purgeable(storage: Storage, path_or_id: str | Path | int) -> PurgeResult:
        """What `purge` would delete, without deleting it; raises the errors `purge` would."""
        return Sources._find_purgeable(storage, path_or_id)[0]

    @staticmethod
    def purge(storage: Storage, path_or_id: str | Path | int) -> PurgeResult:
        """Permanently delete a removed source, or a removed file, on demand.

        `path_or_id` is a source id or path, or the path of a file inside a source.
        The target must already be in the 'removed' state - whether or not its
        retention window has elapsed - and anything else (an active source or file)
        raises SourceNotRemovedError. Raises SourceNotFoundError if nothing matches.
        """
        result, source_row, document_index_id = Sources._find_purgeable(storage, path_or_id)
        if source_row is not None:
            Sources._delete_sources(storage, [source_row], trigger="manual")
        else:
            assert document_index_id is not None
            Sources._delete_document_rows(
                storage, {document_index_id}, trigger="manual", path=result.path
            )
        return result
