"""SQLite implementation of `vethuq_core.storage.base.Storage`.

Each method delegates to the same-purpose query method in
`vethuq_core.db.queries`, so the SQL stays in one place.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path

from vethuq_core.db import Db
from vethuq_core.db.queries import Document, Index, Integrity, Ocr, Settings, Source, Stats


class _SourceStoreMixin:
    _conn: sqlite3.Connection

    def get_source_by_path(self, path: str) -> sqlite3.Row | None:
        return Source.get_by_path(self._conn, path)

    def get_source_by_id(self, source_id: int) -> sqlite3.Row | None:
        return Source.get_by_id(self._conn, source_id)

    def get_active_source_by_id(self, source_id: int) -> sqlite3.Row | None:
        return Source.get_active_by_id(self._conn, source_id)

    def get_active_source_by_path(self, path: str) -> sqlite3.Row | None:
        return Source.get_active_by_path(self._conn, path)

    def reactivate_source(self, source_id: int, source_type: str, added_at: str) -> None:
        return Source.reactivate(self._conn, source_id, source_type, added_at)

    def insert_source(self, path: str, source_type: str, added_at: str) -> int:
        return Source.insert(self._conn, path, source_type, added_at)

    def list_source_rows(self, include_inactive: bool) -> list[sqlite3.Row]:
        return Source.list_rows(self._conn, include_inactive)

    def soft_delete_source(self, source_id: int, removed_at: str) -> None:
        return Source.soft_delete(self._conn, source_id, removed_at)

    def list_expired_removed_sources(self, cutoff: str) -> list[sqlite3.Row]:
        return Source.list_expired_removed(self._conn, cutoff)

    def delete_sources_by_ids(self, source_ids: list[int]) -> None:
        return Source.delete_by_ids(self._conn, source_ids)

    def clear_index_run_targets(self, stale_targets: list[str]) -> None:
        return Source.clear_index_run_targets(self._conn, stale_targets)

    def update_source_scan_status(self, source_id: int, status: str, last_scanned_at: str) -> None:
        return Source.update_scan_status(self._conn, source_id, status, last_scanned_at)


class _DocumentStoreMixin:
    _conn: sqlite3.Connection

    def get_document_id_for_index_row(self, document_index_id: int) -> sqlite3.Row | None:
        return Document.get_id_for_index_row(self._conn, document_index_id)

    def list_document_index_peers(self, document_id: int, exclude_id: int) -> list[sqlite3.Row]:
        return Document.list_index_peers(self._conn, document_id, exclude_id)

    def reassign_pdf_pages_document(
        self, old_document_index_id: int, new_document_index_id: int
    ) -> None:
        return Document.reassign_pdf_pages(self._conn, old_document_index_id, new_document_index_id)

    def reassign_image_pages_document(
        self, old_document_index_id: int, new_document_index_id: int
    ) -> None:
        return Document.reassign_image_pages(
            self._conn,
            old_document_index_id,
            new_document_index_id,
        )

    def document_index_references_document(self, document_id: int) -> bool:
        return Document.index_references_document(self._conn, document_id)

    def delete_document(self, document_id: int) -> None:
        return Document.delete(self._conn, document_id)

    def insert_document(self, created_at: str) -> int:
        return Document.insert(self._conn, created_at)

    def delete_document_phases(self, document_id: int) -> None:
        return Document.delete_phases(self._conn, document_id)

    def list_document_index_rows_for_sources(self, source_ids: list[int]) -> list[sqlite3.Row]:
        return Document.list_index_rows_for_sources(self._conn, source_ids)

    def delete_pdf_pages_for_document(self, document_index_id: int) -> None:
        return Document.delete_pdf_pages(self._conn, document_index_id)

    def delete_image_pages_for_document(self, document_index_id: int) -> None:
        return Document.delete_image_pages(self._conn, document_index_id)

    def delete_document_index_for_sources(self, source_ids: list[int]) -> None:
        return Document.delete_index_for_sources(self._conn, source_ids)

    def list_expired_removed_document_index_rows(self, cutoff: str) -> list[sqlite3.Row]:
        return Document.list_expired_removed_index_rows(self._conn, cutoff)

    def list_document_index_rows_by_ids(self, ids: list[int]) -> list[sqlite3.Row]:
        return Document.list_index_rows_by_ids(self._conn, ids)

    def delete_document_index_by_ids(self, ids: list[int]) -> None:
        return Document.delete_index_by_ids(self._conn, ids)

    def find_duplicate_document_index(self, sha256: str, exclude_id: int) -> sqlite3.Row | None:
        return Document.find_duplicate_index(self._conn, sha256, exclude_id)

    def get_document_index_by_path(self, file_path: str) -> sqlite3.Row | None:
        return Document.get_index_by_path(self._conn, file_path)

    def get_document_index_id_by_path(self, file_path: str) -> sqlite3.Row | None:
        return Document.get_index_id_by_path(self._conn, file_path)

    def upsert_document_index(
        self,
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
        return Document.upsert_index(
            self._conn,
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
        )

    def fail_stuck_processing_document_index(self, message: str, now: str) -> None:
        return Document.fail_stuck_processing_index(self._conn, message, now)

    def list_tracked_document_index_rows(self, source_id: int) -> list[sqlite3.Row]:
        return Document.list_tracked_index_rows(self._conn, source_id)

    def update_document_index_path(
        self,
        row_id: int,
        new_path: str,
        mtime: float,
        file_size_bytes: int,
        created_at: str,
        modified_at: str,
    ) -> None:
        return Document.update_index_path(
            self._conn,
            row_id,
            new_path,
            mtime,
            file_size_bytes,
            created_at,
            modified_at,
        )

    def mark_document_index_removed(self, row_id: int, removed_at: str) -> None:
        return Document.mark_index_removed(self._conn, row_id, removed_at)

    def mark_document_index_indexed(self, document_id: int, now: str) -> None:
        return Document.mark_indexed(self._conn, document_id, now)

    def mark_document_index_error(self, document_id: int, message: str, now: str) -> None:
        return Document.mark_error(self._conn, document_id, message, now)

    def mark_document_index_unsupported(self, document_id: int, message: str, now: str) -> None:
        return Document.mark_unsupported(self._conn, document_id, message, now)

    def get_document_index_metrics_stats(self, document_id: int) -> sqlite3.Row:
        return Document.get_index_metrics_stats(self._conn, document_id)

    def get_page_confidences(self, file_type: str, document_id: int) -> list[sqlite3.Row]:
        return Document.get_page_confidences(self._conn, file_type, document_id)

    def get_pdf_page_sources(self, document_id: int) -> list[sqlite3.Row]:
        return Document.get_pdf_page_sources(self._conn, document_id)

    def get_document_index_pending_check(self, file_path: str) -> sqlite3.Row | None:
        return Document.get_index_pending_check(self._conn, file_path)

    def update_document_index_retry_stats(
        self, document_id: int, retry_count: int, peak_memory_mb: float, cpu_percent: float
    ) -> None:
        return Document.update_index_retry_stats(
            self._conn,
            document_id,
            retry_count,
            peak_memory_mb,
            cpu_percent,
        )

    def insert_pdf_pages(self, rows: list[tuple]) -> None:
        return Document.insert_pdf_pages(self._conn, rows)

    def insert_image_page(
        self,
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
        return Document.insert_image_page(
            self._conn,
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
        )

    def count_document_index_by_status(self, source_id: int) -> list[sqlite3.Row]:
        return Document.count_index_by_status(self._conn, source_id)

    def get_document_result_rows(self, source_id: int) -> list[sqlite3.Row]:
        return Document.get_result_rows(self._conn, source_id)

    def search_indexed_pdf_pages(self, like_pattern: str) -> list[sqlite3.Row]:
        return Document.search_indexed_pdf_pages(self._conn, like_pattern)

    def search_indexed_image_pages(self, like_pattern: str) -> list[sqlite3.Row]:
        return Document.search_indexed_image_pages(self._conn, like_pattern)

    def search_candidate_pdf_pages(self, match_expr: str | None) -> list[sqlite3.Row]:
        return Document.search_candidate_pdf_pages(self._conn, match_expr)

    def search_candidate_image_pages(self, match_expr: str | None) -> list[sqlite3.Row]:
        return Document.search_candidate_image_pages(self._conn, match_expr)

    def search_fulltext_pdf_pages(self, match_expr: str) -> list[sqlite3.Row]:
        return Document.search_fulltext_pdf_pages(self._conn, match_expr)

    def search_fulltext_image_pages(self, match_expr: str) -> list[sqlite3.Row]:
        return Document.search_fulltext_image_pages(self._conn, match_expr)

    def search_proximity_pdf_pages(self, match_expr: str) -> list[sqlite3.Row]:
        return Document.search_proximity_pdf_pages(self._conn, match_expr)

    def search_proximity_image_pages(self, match_expr: str) -> list[sqlite3.Row]:
        return Document.search_proximity_image_pages(self._conn, match_expr)

    def get_pdf_term_highlights(self, match_expr: str, page_ids: list[int]) -> dict[int, str]:
        return Document.get_pdf_term_highlights(self._conn, match_expr, page_ids)

    def get_image_term_highlights(self, match_expr: str, page_ids: list[int]) -> dict[int, str]:
        return Document.get_image_term_highlights(self._conn, match_expr, page_ids)

    def get_pdf_page_counts_by_document(self) -> list[sqlite3.Row]:
        return Document.get_pdf_page_counts(self._conn)

    def refresh_document_file_path(self, document_id: int) -> None:
        return Document.refresh_file_path(self._conn, document_id)


class _SettingsStoreMixin:
    _conn: sqlite3.Connection

    def get_setting_value(self, key: str) -> str | None:
        return Settings.get_value(self._conn, key)

    def upsert_setting(self, key: str, value: str) -> None:
        return Settings.upsert(self._conn, key, value)


class _StatsStoreMixin:
    _conn: sqlite3.Connection

    def get_processing_metrics_row(
        self, phase: int, file_type: str, size_bucket: str
    ) -> sqlite3.Row | None:
        return Stats.get_processing_metrics_row(self._conn, phase, file_type, size_bucket)

    def get_processing_metrics_budget_row(
        self, phase: int, file_type: str, size_bucket: str
    ) -> sqlite3.Row | None:
        return Stats.get_processing_metrics_budget_row(self._conn, phase, file_type, size_bucket)

    def insert_processing_metrics(
        self,
        phase: int,
        file_type: str,
        size_bucket: str,
        duration: float,
        peak_memory_mb: float,
        cpu_percent: float,
        updated_at: str,
    ) -> None:
        return Stats.insert_processing_metrics(
            self._conn,
            phase,
            file_type,
            size_bucket,
            duration,
            peak_memory_mb,
            cpu_percent,
            updated_at,
        )

    def update_processing_metrics(
        self,
        phase: int,
        file_type: str,
        size_bucket: str,
        document_count: int,
        avg_duration_seconds: float,
        avg_peak_memory_mb: float,
        avg_cpu_percent: float,
        updated_at: str,
    ) -> None:
        return Stats.update_processing_metrics(
            self._conn,
            phase,
            file_type,
            size_bucket,
            document_count,
            avg_duration_seconds,
            avg_peak_memory_mb,
            avg_cpu_percent,
            updated_at,
        )

    def get_confidence_metrics_row(self, file_type: str, process_type: str) -> sqlite3.Row | None:
        return Stats.get_confidence_metrics_row(self._conn, file_type, process_type)

    def insert_confidence_metrics(
        self,
        file_type: str,
        process_type: str,
        page_count: int,
        avg_confidence: float,
        updated_at: str,
    ) -> None:
        return Stats.insert_confidence_metrics(
            self._conn,
            file_type,
            process_type,
            page_count,
            avg_confidence,
            updated_at,
        )

    def update_confidence_metrics(
        self,
        file_type: str,
        process_type: str,
        page_count: int,
        avg_confidence: float,
        updated_at: str,
    ) -> None:
        return Stats.update_confidence_metrics(
            self._conn,
            file_type,
            process_type,
            page_count,
            avg_confidence,
            updated_at,
        )

    def list_processing_metrics(self) -> list[sqlite3.Row]:
        return Stats.list_processing_metrics(self._conn)

    def list_confidence_metrics(self) -> list[sqlite3.Row]:
        return Stats.list_confidence_metrics(self._conn)

    def clear_processing_metrics(self) -> None:
        return Stats.clear_processing_metrics(self._conn)

    def clear_confidence_metrics(self) -> None:
        return Stats.clear_confidence_metrics(self._conn)

    def get_processing_metrics_avg_duration_by_file_type(self, phase: int) -> list[sqlite3.Row]:
        return Stats.get_processing_metrics_avg_duration_by_file_type(self._conn, phase)


class _IndexRunStoreMixin:
    _conn: sqlite3.Connection

    def list_index_runs(self, target: str | None, limit: int) -> list[sqlite3.Row]:
        return Index.list_runs(self._conn, target, limit)

    def insert_index_run(
        self,
        target: str | None,
        mode: str,
        pid: int,
        total_files: int,
        workers: int,
        started_at: str,
    ) -> int:
        return Index.insert_run(self._conn, target, mode, pid, total_files, workers, started_at)

    def fail_all_running_index_runs(self, completed_at: str) -> None:
        return Index.fail_all_running(self._conn, completed_at)

    def end_running_index_run(
        self,
        run_id: int,
        status: str,
        total_files: int,
        processed_files: int,
        failed_files: int,
        completed_at: str,
    ) -> None:
        return Index.end_running(
            self._conn,
            run_id,
            status,
            total_files,
            processed_files,
            failed_files,
            completed_at,
        )

    def fail_index_run(self, run_id: int, completed_at: str) -> None:
        return Index.fail_run(self._conn, run_id, completed_at)


class _OcrStoreMixin:
    _conn: sqlite3.Connection

    def get_ocr_document_file_size(self, document_index_id: int) -> sqlite3.Row | None:
        return Ocr.get_document_file_size(self._conn, document_index_id)

    def list_ocr_pages_short_of_phase(
        self, table: str, max_phase: int, source_ids: Sequence[int]
    ) -> list[sqlite3.Row]:
        return Ocr.Page.list_short_of_phase(self._conn, table, max_phase, source_ids)

    def get_ocr_page_text_row(self, table: str, page_id: int) -> sqlite3.Row | None:
        return Ocr.Page.get_text_row(self._conn, table, page_id)

    def update_ocr_page_text(
        self,
        table: str,
        page_id: int,
        ocr_text: str,
        confidence: float,
        ocr_phase: int,
        ocr_angles: str,
    ) -> None:
        return Ocr.Page.update_text(
            self._conn,
            table,
            page_id,
            ocr_text,
            confidence,
            ocr_phase,
            ocr_angles,
        )

    def mark_ocr_page_phase_done(self, table: str, phase: int, page_id: int) -> None:
        return Ocr.Page.mark_phase_done(self._conn, table, phase, page_id)

    def count_ocr_pages_short_of_phase(self, table: str, document_id: int, phase: int) -> int:
        return Ocr.Page.count_short_of_phase(self._conn, table, document_id, phase)

    def list_ocr_phase_progress_rows(
        self, table: str, source_ids: Sequence[int]
    ) -> list[sqlite3.Row]:
        return Ocr.Phase.list_progress_rows(self._conn, table, source_ids)

    def count_ocr_documents_short_of_phase(
        self, file_type: str, phase: int, source_ids: Sequence[int]
    ) -> int:
        return Ocr.Phase.count_documents_short_of(self._conn, file_type, phase, source_ids)

    def start_ocr_document_phase(self, document_id: int, phase: int, started_at: str) -> None:
        return Ocr.Phase.start_document(self._conn, document_id, phase, started_at)

    def get_ocr_document_phase_work(self, document_id: int, phase: int) -> sqlite3.Row | None:
        return Ocr.Phase.get_document_work(self._conn, document_id, phase)

    def update_ocr_document_phase_work(
        self,
        document_id: int,
        phase: int,
        duration_seconds: float,
        peak_memory_mb: float,
        cpu_percent: float,
    ) -> None:
        return Ocr.Phase.update_document_work(
            self._conn,
            document_id,
            phase,
            duration_seconds,
            peak_memory_mb,
            cpu_percent,
        )

    def get_ocr_document_phase_completion(self, document_id: int, phase: int) -> sqlite3.Row | None:
        return Ocr.Phase.get_document_completion(self._conn, document_id, phase)

    def complete_ocr_document_phase(self, document_id: int, phase: int, completed_at: str) -> None:
        return Ocr.Phase.complete_document(self._conn, document_id, phase, completed_at)


class _IntegrityStoreMixin:
    _conn: sqlite3.Connection

    def run_integrity_check_pragma(self) -> list[str]:
        return Integrity.run_pragma(self._conn)


class SqliteStorage(
    _SourceStoreMixin,
    _DocumentStoreMixin,
    _SettingsStoreMixin,
    _StatsStoreMixin,
    _IndexRunStoreMixin,
    _OcrStoreMixin,
    _IntegrityStoreMixin,
):
    """A `Storage` over one SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, db_path: Path | None = None, *, check_same_thread: bool = True) -> SqliteStorage:
        """Connect (creating/migrating the schema as needed) and wrap the connection."""
        return cls(Db.connect(db_path, check_same_thread=check_same_thread))

    def transaction(self) -> AbstractContextManager[sqlite3.Connection]:
        # sqlite3 commits on success and rolls back on error, leaving the connection open.
        return self._conn

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
