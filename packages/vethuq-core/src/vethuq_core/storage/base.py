"""The storage-access interface: what the rest of VethuQ needs from "the database".

Application code (sources, settings, stats, indexing, OCR, search, the CLI, UI and
Python library) depends only on `Storage` and never on `sqlite3` or
`vethuq_core.db`. `Storage` is the union of small per-table repositories, so a
collaborator can depend on just the slice it needs (e.g. `SettingsStore`).
`vethuq_core.storage.sqlite.SqliteStorage` is the SQLite implementation, backed
by the query classes in `vethuq_core.db.queries`.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol


class SearchIndexRebuildError(Exception):
    """Rebuilding one search index failed; the message is the database's own."""


class Row(Protocol):
    """A result row, addressable by column name or position (like `sqlite3.Row`)."""

    def __getitem__(self, key: Any, /) -> Any: ...

    def keys(self) -> list[str]: ...


class SourceStore(Protocol):
    """Storage operations for the `sources` table."""

    def get_source_by_path(self, path: str) -> Row | None: ...

    def get_source_by_id(self, source_id: int) -> Row | None: ...

    def get_active_source_by_id(self, source_id: int) -> Row | None: ...

    def get_active_source_by_path(self, path: str) -> Row | None: ...

    def reactivate_source(self, source_id: int, source_type: str, added_at: str) -> None: ...

    def insert_source(self, path: str, source_type: str, added_at: str) -> int: ...

    def set_source_languages(self, source_id: int, languages: str | None) -> None: ...

    def list_source_rows(self, include_inactive: bool) -> Sequence[Row]: ...

    def soft_delete_source(self, source_id: int, removed_at: str) -> None: ...

    def list_expired_removed_sources(self, cutoff: str) -> Sequence[Row]: ...

    def delete_sources_by_ids(self, source_ids: list[int]) -> None: ...

    def clear_index_run_targets(self, stale_targets: list[str]) -> None: ...

    def update_source_scan_status(
        self, source_id: int, status: str, last_scanned_at: str
    ) -> None: ...


class DocumentStore(Protocol):
    """Storage operations for documents, indexed files and their pages."""

    def get_document_id_for_index_row(self, document_index_id: int) -> Row | None: ...

    def list_document_index_peers(self, document_id: int, exclude_id: int) -> Sequence[Row]: ...

    def reassign_pdf_pages_document(
        self, old_document_index_id: int, new_document_index_id: int
    ) -> None: ...

    def reassign_image_pages_document(
        self, old_document_index_id: int, new_document_index_id: int
    ) -> None: ...

    def document_index_references_document(self, document_id: int) -> bool: ...

    def delete_document(self, document_id: int) -> None: ...

    def insert_document(self, created_at: str) -> int: ...

    def delete_document_phases(self, document_id: int) -> None: ...

    def list_document_index_rows_for_sources(self, source_ids: list[int]) -> Sequence[Row]: ...

    def delete_pdf_pages_for_document(self, document_index_id: int) -> None: ...

    def delete_image_pages_for_document(self, document_index_id: int) -> None: ...

    def delete_document_index_for_sources(self, source_ids: list[int]) -> None: ...

    def list_expired_removed_document_index_rows(self, cutoff: str) -> Sequence[Row]: ...

    def list_document_index_rows_by_ids(self, ids: list[int]) -> Sequence[Row]: ...

    def delete_document_index_by_ids(self, ids: list[int]) -> None: ...

    def find_duplicate_document_index(self, sha256: str, exclude_id: int) -> Row | None: ...

    def get_document_index_by_path(self, file_path: str) -> Row | None: ...

    def get_document_index_id_by_path(self, file_path: str) -> Row | None: ...

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
    ) -> bool: ...

    def fail_stuck_processing_document_index(self, message: str, now: str) -> int: ...

    def find_document_index_row_for_reindex(
        self, *, row_id: int | None = None, file_path: str | None = None
    ) -> Row | None: ...

    def reset_document_index_for_reindex(
        self, source_id: int, file_path: str | None = None
    ) -> int: ...

    def search_index_names(self) -> tuple[str, ...]: ...

    def rebuild_search_index(self, index: str) -> int: ...

    def list_tracked_document_index_rows(self, source_id: int) -> Sequence[Row]: ...

    def update_document_index_path(
        self,
        row_id: int,
        new_path: str,
        mtime: float,
        file_size_bytes: int,
        created_at: str,
        modified_at: str,
    ) -> None: ...

    def mark_document_index_removed(self, row_id: int, removed_at: str) -> None: ...

    def mark_document_index_indexed(self, document_id: int, now: str) -> None: ...

    def mark_document_index_error(self, document_id: int, message: str, now: str) -> None: ...

    def mark_document_index_unsupported(self, document_id: int, message: str, now: str) -> None: ...

    def get_document_index_metrics_stats(self, document_id: int) -> Row: ...

    def get_page_confidences(self, file_type: str, document_id: int) -> Sequence[Row]: ...

    def get_pdf_page_sources(self, document_id: int) -> Sequence[Row]: ...

    def get_page_languages(self, file_ids: Sequence[int]) -> Sequence[Row]: ...

    def get_document_index_pending_check(self, file_path: str) -> Row | None: ...

    def update_document_index_retry_stats(
        self, document_id: int, retry_count: int, peak_memory_mb: float, cpu_percent: float
    ) -> None: ...

    def insert_pdf_pages(self, rows: list[tuple]) -> None: ...

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
    ) -> None: ...

    def count_document_index_by_status(self, source_id: int) -> Sequence[Row]: ...

    def get_document_result_rows(self, source_id: int) -> Sequence[Row]: ...

    def list_source_file_rows(self, source_id: int) -> Sequence[Row]: ...

    def list_page_ocr_state(self, file_type: str, document_id: int) -> Sequence[Row]: ...

    def list_phase_rows(self, logical_document_id: int) -> Sequence[Row]: ...

    def search_indexed_pdf_pages(
        self, like_pattern: str, match_expr: str | None = None
    ) -> Sequence[Row]: ...

    def search_indexed_image_pages(
        self, like_pattern: str, match_expr: str | None = None
    ) -> Sequence[Row]: ...

    def search_lexical_pdf_pages(self, match_expr: str) -> Sequence[Row]: ...

    def search_lexical_image_pages(self, match_expr: str) -> Sequence[Row]: ...

    def search_candidate_pdf_pages(self, match_expr: str | None) -> Sequence[Row]: ...

    def search_candidate_image_pages(self, match_expr: str | None) -> Sequence[Row]: ...

    def search_noise_candidate_pdf_pages(self, match_expr: str | None) -> Sequence[Row]: ...

    def search_noise_candidate_image_pages(self, match_expr: str | None) -> Sequence[Row]: ...

    def search_norm_candidate_pdf_pages(self, match_expr: str | None) -> Sequence[Row]: ...

    def search_norm_candidate_image_pages(self, match_expr: str | None) -> Sequence[Row]: ...

    def search_fulltext_pdf_pages(
        self, match_expr: str, complex_index: bool = False
    ) -> Sequence[Row]: ...

    def search_fulltext_image_pages(
        self, match_expr: str, complex_index: bool = False
    ) -> Sequence[Row]: ...

    def search_proximity_pdf_pages(
        self, match_expr: str, complex_index: bool = False
    ) -> Sequence[Row]: ...

    def search_proximity_image_pages(
        self, match_expr: str, complex_index: bool = False
    ) -> Sequence[Row]: ...

    def has_complex_word_index(self) -> bool: ...

    def get_pdf_term_highlights(
        self, match_expr: str, page_ids: list[int], complex_index: bool = False
    ) -> dict[int, str]: ...

    def get_image_term_highlights(
        self, match_expr: str, page_ids: list[int], complex_index: bool = False
    ) -> dict[int, str]: ...

    def get_pdf_page_counts_by_document(self) -> Sequence[Row]: ...

    def refresh_document_file_path(self, document_id: int) -> None: ...


class SettingsStore(Protocol):
    """Storage operations for the `settings` table."""

    def get_setting_value(self, key: str) -> str | None: ...

    def upsert_setting(self, key: str, value: str) -> None: ...


class StatsStore(Protocol):
    """Storage operations for the processing and confidence metrics."""

    def get_processing_metrics_row(
        self, phase: int, extension: str, size_bucket: str, language: str = "en"
    ) -> Row | None: ...

    def get_processing_metrics_budget_row(
        self, phase: int, extension: str, size_bucket: str
    ) -> Row | None: ...

    def insert_processing_metrics(
        self,
        phase: int,
        file_type: str,
        extension: str,
        size_bucket: str,
        duration: float,
        peak_memory_mb: float,
        cpu_percent: float,
        updated_at: str,
        language: str = "en",
    ) -> None: ...

    def update_processing_metrics(
        self,
        phase: int,
        extension: str,
        size_bucket: str,
        document_count: int,
        avg_duration_seconds: float,
        avg_peak_memory_mb: float,
        avg_cpu_percent: float,
        updated_at: str,
        language: str = "en",
    ) -> None: ...

    def get_confidence_metrics_row(
        self, extension: str, process_type: str, language: str = "en"
    ) -> Row | None: ...

    def insert_confidence_metrics(
        self,
        file_type: str,
        extension: str,
        process_type: str,
        page_count: int,
        avg_confidence: float,
        updated_at: str,
        language: str = "en",
    ) -> None: ...

    def update_confidence_metrics(
        self,
        extension: str,
        process_type: str,
        page_count: int,
        avg_confidence: float,
        updated_at: str,
        language: str = "en",
    ) -> None: ...

    def list_processing_metrics(self, language: str | None = None) -> Sequence[Row]: ...

    def list_confidence_metrics(self, language: str | None = None) -> Sequence[Row]: ...

    def clear_processing_metrics(self) -> None: ...

    def clear_confidence_metrics(self) -> None: ...

    def get_processing_metrics_avg_duration_by_file_type(self, phase: int) -> Sequence[Row]: ...


class IndexRunStore(Protocol):
    """Storage operations for the `index_runs` table."""

    def list_index_runs(self, target: str | None, limit: int) -> Sequence[Row]: ...

    def insert_index_run(
        self,
        target: str | None,
        mode: str,
        pid: int,
        total_files: int,
        workers: int,
        started_at: str,
    ) -> int: ...

    def fail_all_running_index_runs(self, completed_at: str) -> None: ...

    def end_running_index_run(
        self,
        run_id: int,
        status: str,
        total_files: int,
        processed_files: int,
        failed_files: int,
        completed_at: str,
    ) -> None: ...

    def fail_index_run(self, run_id: int, completed_at: str) -> None: ...


class IndexJobStore(Protocol):
    """Storage operations for the `index_jobs` queue the background service works through."""

    def enqueue_index_job(
        self, target: str | None, mode: str, languages: str | None, requested_at: str
    ) -> int: ...

    def list_index_jobs(self, statuses: tuple[str, ...] | None, limit: int) -> Sequence[Row]: ...

    def get_index_job(self, job_id: int) -> Row | None: ...

    def claim_next_index_job(self, started_at: str) -> Row | None: ...

    def mark_index_job_started(self, job_id: int, pid: int, started_at: str) -> None: ...

    def attach_index_job_run(self, job_id: int, run_id: int, pid: int) -> None: ...

    def finish_index_jobs_for_run(
        self, run_id: int, status: str, finished_at: str, error: str | None
    ) -> None: ...

    def finish_index_job(
        self, job_id: int, status: str, finished_at: str, error: str | None
    ) -> None: ...

    def requeue_index_job(self, job_id: int) -> None: ...

    def requeue_running_index_jobs(self) -> int: ...

    def cancel_queued_index_jobs(self, finished_at: str) -> int: ...

    def prune_index_jobs(self, keep: int) -> None: ...


class OcrStore(Protocol):
    """Storage operations for the multi-phase OCR pipeline (pages and per-document phases)."""

    def get_ocr_document_file_size(self, document_index_id: int) -> Row | None: ...

    def list_ocr_pages_short_of_phase(
        self, table: str, max_phase: int, source_ids: Sequence[int]
    ) -> Sequence[Row]: ...

    def get_ocr_page_text_row(self, table: str, page_id: int) -> Row | None: ...

    def update_ocr_page_text(
        self,
        table: str,
        page_id: int,
        ocr_text: str,
        confidence: float,
        ocr_phase: int,
        ocr_angles: str,
    ) -> None: ...

    def mark_ocr_page_phase_done(self, table: str, phase: int, page_id: int) -> None: ...

    def count_ocr_pages_short_of_phase(self, table: str, document_id: int, phase: int) -> int: ...

    def list_ocr_phase_progress_rows(
        self, table: str, source_ids: Sequence[int]
    ) -> Sequence[Row]: ...

    def count_ocr_documents_short_of_phase(
        self, file_type: str, phase: int, source_ids: Sequence[int]
    ) -> int: ...

    def start_ocr_document_phase(self, document_id: int, phase: int, started_at: str) -> None: ...

    def get_ocr_document_phase_work(self, document_id: int, phase: int) -> Row | None: ...

    def update_ocr_document_phase_work(
        self,
        document_id: int,
        phase: int,
        duration_seconds: float,
        peak_memory_mb: float,
        cpu_percent: float,
    ) -> None: ...

    def get_ocr_document_phase_completion(self, document_id: int, phase: int) -> Row | None: ...

    def complete_ocr_document_phase(
        self, document_id: int, phase: int, completed_at: str
    ) -> None: ...

    def replace_document_languages(
        self, document_id: int, rows: Sequence[tuple[str, int, str, str, float | None]]
    ) -> None: ...

    def get_document_languages(self, document_id: int) -> Sequence[Row]: ...

    def update_document_language(
        self,
        document_id: int,
        language: str,
        status: str,
        confidence: float | None,
        error_message: str | None,
        started_at: str | None,
        completed_at: str | None,
    ) -> None: ...

    def list_pending_language_passes(self, source_ids: Sequence[int]) -> Sequence[Row]: ...

    def list_ocr_document_pages(self, table: str, document_id: int) -> Sequence[Row]: ...

    def update_ocr_page_languages(
        self, table: str, page_id: int, language: str, ocr_langs: str
    ) -> None: ...

    def reset_processing_language_passes(self) -> int: ...


class IntegrityStore(Protocol):
    """Storage operations for database integrity checks."""

    def run_integrity_check_pragma(self) -> list[str]: ...


class SemanticStore(Protocol):
    """Storage operations for the semantic search index (page chunk embeddings).

    The embeddings are kept in a store of their own (see `vethuq_core.db.queries.semantic`);
    every call that reads them is for one `model` at one `version` of how text is embedded.
    """

    def list_unembedded_pages(self, model: str, version: str, limit: int) -> Sequence[Row]: ...

    def count_semantic(self, model: str, version: str) -> dict[str, int]: ...

    def replace_semantic_page(
        self,
        kind: str,
        page_id: int,
        model: str,
        version: str,
        chunks: Sequence[tuple[int, int, int, bytes]],
    ) -> None: ...

    def list_semantic_chunks(self, model: str, version: str) -> Sequence[Row]: ...

    def list_semantic_page_rows(self, kind: str, page_ids: Sequence[int]) -> Sequence[Row]: ...

    def purge_stale_semantic(self, model: str, version: str) -> int: ...

    def clear_semantic(self, model: str | None = None) -> int: ...

    def semantic_store_path(self) -> Path | None: ...


class Storage(
    SourceStore,
    DocumentStore,
    SettingsStore,
    StatsStore,
    IndexRunStore,
    IndexJobStore,
    OcrStore,
    IntegrityStore,
    SemanticStore,
    Protocol,
):
    """Everything the application reads from or writes to persistent storage."""

    def transaction(self) -> AbstractContextManager[Any]:
        """Group writes atomically: commit on success, roll back if the block raises."""
        ...

    def commit(self) -> None:
        """Commit any pending writes."""
        ...

    def close(self) -> None:
        """Release the underlying resources. The storage is unusable afterwards."""
        ...
