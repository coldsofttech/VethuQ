"""Per-document indexing bookkeeping: hashing, dedupe, status, and stored pages."""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from vethuq_core.db.queries import Document as DocumentQuery
from vethuq_core.ocr.reader import PageResult
from vethuq_core.source import Source

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentResult:
    file_path: str
    status: str
    error_message: str | None
    confidence: float | None
    started_at: str | None
    completed_at: str | None
    duration: float | None
    duplicate_of_path: str | None

    def to_dict(self) -> dict[str, object]:
        """The machine-readable shape `vethuq index status <source> --json` prints."""
        return {
            "file": self.file_path,
            "status": self.status,
            "confidence": self.confidence,
            "duration": self.duration,
            "error": self.error_message,
            "duplicate_of": self.duplicate_of_path,
        }


class Document:
    CHECKSUM_CHUNK_BYTES = 1024 * 1024

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """Return the SHA-256 hex digest of a file's contents, read in chunks."""
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(Document.CHECKSUM_CHUNK_BYTES), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def capture_timestamps(stat: os.stat_result) -> tuple[str, str]:
        """Return `(created_at, modified_at)` ISO-8601 timestamps from a file's `stat` result.

        `modified_at` is always `st_mtime`. `created_at` uses the OS's actual
        file-birth time where one is exposed - `st_birthtime` (macOS/BSD) or, on
        Windows, `st_ctime` (which is creation time there, not metadata-change
        time as on POSIX). Linux exposes neither via `os.stat`, so `created_at`
        falls back to `st_mtime` there too, same as `modified_at`.
        """
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
        # getattr with a default, not hasattr: `st_birthtime` isn't in typeshed's
        # stat_result (it's only actually present on macOS/BSD at runtime), so a
        # plain attribute access would be a static type error.
        created = getattr(stat, "st_birthtime", None)
        if created is None:
            created = stat.st_ctime if sys.platform == "win32" else stat.st_mtime
        created_at = datetime.fromtimestamp(created, tz=UTC).isoformat()
        return created_at, modified_at

    @staticmethod
    def find_duplicate(conn: sqlite3.Connection, sha256: str, row_id: int) -> sqlite3.Row | None:
        """Return the earliest-indexed `document_index` row (id, document_id) matching `sha256`.

        Excludes `row_id` itself. Used to link a (re)indexed row to an existing
        logical document (`documents.id`) with identical content, rather than
        creating a new one - the earliest-indexed match is used so a whole
        duplicate group always converges on a single `documents` row.
        """
        return DocumentQuery.find_duplicate_index(conn, sha256, row_id)

    @staticmethod
    def has_content_changed(file_path: Path, existing: sqlite3.Row) -> bool:
        """Return whether `file_path`'s content differs from its `document_index` row.

        A file's mtime and size are checked first - if neither moved since it was
        last indexed, its content is assumed unchanged and the (expensive) full
        hash is skipped entirely. Only when mtime or size differ is the SHA-256
        recomputed and compared, to confirm this is an actual content change
        rather than e.g. a touch that left the bytes alone.
        """
        stat = file_path.stat()
        if stat.st_mtime == existing["mtime"] and stat.st_size == existing["file_size_bytes"]:
            return False
        return Document.compute_sha256(file_path) != existing["sha256"]

    @staticmethod
    def upsert(
        conn: sqlite3.Connection, source_id: int, file_path: Path, file_type: str
    ) -> tuple[int, int | None] | None:
        """Claim and insert/reset a document's `document_index` row, linking it to its
        logical document.

        Returns `(row_id, duplicate_source_id)` - `duplicate_source_id` is the id
        of another `document_index` row whose content (by checksum) this one now
        matches; `row_id` is linked to that row's `documents.id` and the caller
        should skip OCR. It's None when this row's content is unique among
        currently indexed documents, in which case it's linked to a brand-new
        `documents` row (or keeps its existing one, if content is unchanged).

        Returns None instead - rather than a tuple - if `file_path`'s row is
        already claimed ('processing') by another concurrently-running index run
        (an overlapping `index run`, or one that hasn't been reconciled yet after
        a crash - see `DocumentQuery.upsert_index` and `IndexRunner._run_worker`).
        The caller must leave the file alone in that case: whichever run holds
        the claim owns processing it, and touching it here would mean the same
        file gets OCR'd twice at once.

        If this document's checksum is changing (its content was modified since
        it was last indexed) and other documents were linked to its old logical
        document, the earliest of them is promoted to take over its OCR pages
        first - see `Sources.promote_surviving_duplicate` - so they keep reusing text
        that actually matches their (unchanged) bytes instead of losing it when
        this row moves on to different content. If that leaves the old logical
        document with no other physical row referencing it, it's pruned.
        """
        from vethuq_core.source import Sources

        existing = DocumentQuery.get_index_by_path(conn, str(file_path))
        if existing is not None and existing["status"] == "processing":
            return None

        started_at = datetime.now(UTC).isoformat()
        stat = file_path.stat()
        file_size_bytes = stat.st_size
        mtime = stat.st_mtime
        created_at, modified_at = Document.capture_timestamps(stat)
        sha256 = Document.compute_sha256(file_path)

        if existing is not None and existing["sha256"] != sha256:
            Sources.promote_surviving_duplicate(conn, existing["id"], set())

        existing_id = existing["id"] if existing is not None else -1
        duplicate_source = Document.find_duplicate(conn, sha256, existing_id)

        old_document_id = existing["document_id"] if existing is not None else None
        is_new_document = False
        if duplicate_source is not None:
            document_id = duplicate_source["document_id"]
        elif existing is not None and existing["sha256"] == sha256:
            document_id = old_document_id
        else:
            document_id = DocumentQuery.insert(conn, started_at)
            is_new_document = True

        claimed = DocumentQuery.upsert_index(
            conn,
            source_id,
            document_id,
            str(file_path),
            file_type,
            started_at,
            file_size_bytes,
            sha256,
            mtime,
            created_at,
            modified_at,
        )
        if not claimed:
            # Lost the claim race between the check above and this write (another
            # run claimed it in between) - nothing else can reference a document
            # row created just now for this attempt, so drop it rather than
            # leaving it orphaned.
            if is_new_document:
                DocumentQuery.delete(conn, document_id)
            return None

        if duplicate_source is None:
            # Re-indexing starts the document over from its quick pass. Only done
            # once the claim is won, so a lost race never wipes the other run's phases.
            DocumentQuery.delete_phases(conn, document_id)
        if old_document_id is not None and old_document_id != document_id:
            Sources.prune_orphaned_documents(conn, {old_document_id})
        Sources.refresh_document_paths(conn, {document_id, old_document_id} - {None})

        row = DocumentQuery.get_index_id_by_path(conn, str(file_path))
        assert row is not None
        row_id = row["id"]
        return row_id, (duplicate_source["id"] if duplicate_source is not None else None)

    @staticmethod
    def reconcile_renamed_and_removed(
        conn: sqlite3.Connection, source: Source, disk_files: list[Path]
    ) -> set[str]:
        """Detect files renamed/moved within `source`, and files missing from it.

        Compares `source`'s tracked (non-'removed') `document_index` rows
        against `disk_files` (every supported file currently found under this
        source). A brand-new path whose checksum exactly matches a tracked path
        that's no longer on disk is treated as that file renamed or moved: the
        existing row's `file_path` (and mtime/size) is updated in place, with no
        OCR re-run, rather than indexing it as an unrelated new file and leaving
        the old row to be purged as removed.

        When more than one candidate shares a checksum (e.g. two files with
        identical content, one deleted and one renamed), pairing is done in a
        deterministic but otherwise arbitrary order (tracked rows by id, new
        paths alphabetically) rather than left unmatched. This is safe even
        when "wrong": whichever row ends up representing that content, a
        document that owned OCR pages other rows were deduped against still
        hands them off correctly via `Sources.promote_surviving_duplicate` once it's
        actually purged, so no OCR text is ever lost or misattributed.

        A tracked path that's gone missing and isn't claimed by a rename is
        marked 'removed' (with `removed_at` set) so `Sources.purge_expired_documents`
        can clean it up after the retention window, promoting a surviving
        duplicate first if other documents had been deduped against it.

        Returns the set of new on-disk paths (as strings) claimed by a rename,
        so the caller can skip (re-)indexing them.
        """
        disk_path_strs = {str(path) for path in disk_files}
        tracked = DocumentQuery.list_tracked_index_rows(conn, source.id)
        tracked_paths = {row["file_path"] for row in tracked}

        missing_rows = [row for row in tracked if row["file_path"] not in disk_path_strs]
        new_paths = sorted(disk_path_strs - tracked_paths)

        claimed_paths: set[str] = set()
        claimed_row_ids: set[int] = set()

        if missing_rows and new_paths:
            new_sha256s = {path: Document.compute_sha256(Path(path)) for path in new_paths}
            missing_by_sha256: dict[str, list[sqlite3.Row]] = {}
            for row in sorted(missing_rows, key=lambda r: r["id"]):
                missing_by_sha256.setdefault(row["sha256"], []).append(row)
            new_by_sha256: dict[str, list[str]] = {}
            for path in new_paths:
                new_by_sha256.setdefault(new_sha256s[path], []).append(path)

            for sha256, rows in missing_by_sha256.items():
                matching_paths = new_by_sha256.get(sha256)
                if not matching_paths:
                    continue
                for row, new_path in zip(rows, matching_paths, strict=False):
                    stat = Path(new_path).stat()
                    created_at, modified_at = Document.capture_timestamps(stat)
                    DocumentQuery.update_index_path(
                        conn,
                        row["id"],
                        new_path,
                        stat.st_mtime,
                        stat.st_size,
                        created_at,
                        modified_at,
                    )
                    claimed_paths.add(new_path)
                    claimed_row_ids.add(row["id"])

        removed_at = datetime.now(UTC).isoformat()
        for row in missing_rows:
            if row["id"] in claimed_row_ids:
                continue
            DocumentQuery.mark_index_removed(conn, row["id"], removed_at)

        from vethuq_core.source import Sources

        Sources.refresh_document_paths(conn, {row["document_id"] for row in missing_rows})
        return claimed_paths

    @staticmethod
    def mark_indexed(conn: sqlite3.Connection, document_id: int) -> None:
        DocumentQuery.mark_indexed(conn, document_id, datetime.now(UTC).isoformat())

    @staticmethod
    def mark_duplicate(conn: sqlite3.Connection, document_id: int) -> None:
        """Mark a document as indexed via a checksum match instead of running OCR on it.

        Its `document_id` (the logical document it shares with the matched
        content) was already set by `Document.upsert`, so there's nothing left
        to link here beyond the status itself.
        """
        DocumentQuery.mark_indexed(conn, document_id, datetime.now(UTC).isoformat())

    @staticmethod
    def mark_error(conn: sqlite3.Connection, document_id: int, message: str) -> None:
        DocumentQuery.mark_error(conn, document_id, message, datetime.now(UTC).isoformat())

    @staticmethod
    def store_pages(
        conn: sqlite3.Connection, document_id: int, file_type: str, pages: list[PageResult]
    ) -> None:
        """Replace a document's OCR pages with freshly (re)extracted `pages`."""
        if file_type == "pdf":
            DocumentQuery.delete_pdf_pages(conn, document_id)
            DocumentQuery.insert_pdf_pages(
                conn,
                [
                    (
                        document_id,
                        page_number,
                        page.text,
                        page.confidence,
                        page.source,
                        page.ocr_engine,
                        page.language,
                        page.image_width,
                        page.image_height,
                        *page.phase_columns(),
                    )
                    for page_number, page in enumerate(pages, start=1)
                ],
            )
        elif file_type in ("doc", "docx", "xls", "xlsx"):
            page = pages[0]
            DocumentQuery.delete_office_pages(conn, document_id)
            DocumentQuery.insert_office_page(
                conn,
                document_id,
                page.text,
                page.confidence,
                page.source,
                page.ocr_engine,
                page.language,
                page.image_width,
                page.image_height,
            )
        else:
            page = pages[0]
            DocumentQuery.delete_image_pages(conn, document_id)
            DocumentQuery.insert_image_page(
                conn,
                document_id,
                page.text,
                page.confidence,
                page.ocr_engine,
                page.language,
                page.image_width,
                page.image_height,
                *page.phase_columns(),
            )

    @staticmethod
    def get_results(conn: sqlite3.Connection, source_id: int) -> list[DocumentResult]:
        """Return one result per document indexed under `source_id`, most recent first.

        `confidence` is the average across a document's pages (there's only one for
        an image; a PDF may have several), and is None for documents that aren't
        (yet) successfully indexed. For a duplicate (`duplicate_of_path` is not
        None), the pages - and so the confidence - are the original's, since a
        duplicate has none of its own. `duration` (in seconds) is derived from
        `started_at`/`completed_at` and is None while a document is still pending.
        """
        # `canonical_id` is whichever `document_index` row sharing this one's
        # `document_id` actually carries OCR pages of its own (itself, if it does)
        # - duplicates are detected globally, so that carrier may belong to a
        # different source than `source_id`.
        rows = DocumentQuery.get_result_rows(conn, source_id)

        results = []
        for row in rows:
            confidence = None
            if row["status"] == "indexed":
                scores = [
                    page["confidence"]
                    for page in DocumentQuery.get_page_confidences(
                        conn, row["file_type"], row["canonical_id"]
                    )
                ]
                confidence = sum(scores) / len(scores) if scores else None

            duration = None
            if row["started_at"] and row["completed_at"]:
                duration = (
                    datetime.fromisoformat(row["completed_at"])
                    - datetime.fromisoformat(row["started_at"])
                ).total_seconds()

            results.append(
                DocumentResult(
                    file_path=row["file_path"],
                    status=row["status"],
                    error_message=row["error_message"],
                    confidence=confidence,
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    duration=duration,
                    duplicate_of_path=row["duplicate_of_path"],
                )
            )
        return results
