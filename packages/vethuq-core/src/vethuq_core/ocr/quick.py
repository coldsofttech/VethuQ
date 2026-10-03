"""The quick (first) OCR pass: every file read once, upright, so it's searchable fast."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    pass

from vethuq_core.logs import Logs
from vethuq_core.ocr.document import Document
from vethuq_core.ocr.metrics import Metrics
from vethuq_core.ocr.page import PageOcr
from vethuq_core.ocr.pending import Pending, PendingFile
from vethuq_core.ocr.scheduler import Scheduler
from vethuq_core.readers import (
    FileRemovedError,
    PageResult,
    Reader,
    Readers,
    UnreadableFileError,
)
from vethuq_core.settings import IndexSettings, OcrSettings
from vethuq_core.sources import Source
from vethuq_core.storage import Storage

_logger = Logs.get_logger("index")


class _Wait:
    """Sentinel: this slot is idle - parked past the current active worker count."""


_WAIT = _Wait()


class Quick:
    IDLE_POLL_SECONDS = 0.5

    @staticmethod
    def run_with_retries(
        storage: Storage, reader: Reader, file_path: Path
    ) -> tuple[list[PageResult] | None, int, Exception | None]:
        """Retry OCR itself (no DB writes) up to the configured attempt count.

        Kept separate from committing a result so a run of failed OCR attempts
        never touches the database until there's something final to record -
        see `Quick.finalize_result`. Returns `(pages, attempts_used,
        last_exception)`; `pages` is None if every attempt failed. A file that
        vanished, is password-protected, or is corrupted (`UnreadableFileError`,
        or a bare `FileNotFoundError`) fails immediately without further attempts,
        since retrying can't change the outcome.
        """
        max_attempts = 1 + OcrSettings.get_retry_attempts(storage)
        attempt = 0
        last_exc: Exception | None = None
        pages: list[PageResult] | None = None
        while attempt < max_attempts and pages is None:
            attempt += 1
            try:
                pages = PageOcr.ocr_document(storage, reader, file_path)
            except UnreadableFileError as exc:
                # Vanished, password-protected, or corrupted - the same on every
                # attempt, so retrying would only repeat the failure.
                last_exc = exc
                break
            except FileNotFoundError as exc:
                last_exc = FileRemovedError(file_path)
                last_exc.__cause__ = exc
                break
            except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort the batch
                last_exc = exc
        return pages, attempt, last_exc

    @staticmethod
    def finalize_result(
        storage: Storage,
        document_id: int,
        file_type: str,
        pages: list[PageResult] | None,
        attempts_used: int,
        last_exc: Exception | None,
        peak_memory_mb: float,
        cpu_percent: float,
    ) -> bool:
        """Commit one document's processing result as a single atomic transaction.

        On success, the pages, the 'indexed' status transition, and the
        processing/confidence metrics updates land together in one commit; on
        failure, only the 'error' status and retry stats are written - the
        previous run's pages (if any) are left untouched rather than cleared
        ahead of a retry that might not succeed.

        Wrapping the writes in `storage.transaction()` means any exception raised
        while writing this - not just an OCR failure, which is handled by
        `pages`/`last_exc` before this is even called, but a DB error partway
        through the writes themselves - rolls back everything written since entry
        rather than leaving a partial result committed later alongside whatever
        this connection writes next. The row is left claimed
        ('processing') in that case, for a future run to retry rather than ever
        being readable as 'indexed' with missing pages/metrics.

        Returns whether the document was indexed successfully.
        """
        with storage.transaction():
            storage.update_document_index_retry_stats(
                document_id, attempts_used - 1, peak_memory_mb, cpu_percent
            )
            if pages is None:
                Document.mark_error(storage, document_id, str(last_exc))
                return False
            Document.store_pages(storage, document_id, file_type, pages)
            Document.mark_indexed(storage, document_id)
            Metrics.update_processing(storage, document_id, file_type)
            Metrics.update_confidence(storage, document_id, file_type)
            return True

    @staticmethod
    def run(
        storage: Storage,
        source: Source,
        *,
        only_new_files: bool = False,
        only_failed: bool = False,
        on_file_done: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[str]:
        """Run OCR over supported files under `source` and index the results.

        Unsupported files are never OCR'd but are recorded as 'unsupported' rows (see
        `Document.record_unsupported`). Per-file OCR failures are recorded
        on that file's `document_index` row (status='error') without aborting the
        rest of the source; `sources.status` reflects the overall outcome.

        When `only_new_files` is True, a file that already has a successful
        `document_index` row is left untouched unless its content has changed
        since - checked via mtime/size first, falling back to a full checksum
        comparison when either moved. A changed file is treated as modified and
        (re)processed just like a new one. Use this for a source that's already
        been indexed, to pick up files added or edited since the last run
        without redoing OCR on everything else. When False (the default), every
        supported file under the source is (re)processed unconditionally -
        appropriate for a source that's freshly added or reactivated after
        removal.

        When `only_failed` is True, only files whose `document_index` row has
        status='error' are (re)processed - new and already-indexed files are
        left untouched. Use this to retry failures without touching anything
        else. Takes precedence over `only_new_files` if both are set.

        When `only_new_files` is True (and `only_failed` is False), this also
        reconciles the source's tracked files against what's actually on disk
        before processing anything - see `Document.reconcile_renamed_and_removed`.
        A file that was renamed/moved within the source is detected by content
        and has its `document_index` row updated in place rather than being
        reprocessed as new; a tracked file that's gone missing (and wasn't
        claimed by a rename) is marked 'removed' for later cleanup by
        `Sources.purge_expired_documents`.

        `on_file_done`, when given, is called with a file's path immediately after
        it's (re)processed - used to report progress. `should_stop`, when given,
        is checked before each file and stops the source early (leaving remaining
        files untouched) if it returns True.

        Returns the paths of the files actually (re)processed in this call.
        """
        root = Path(source.path)
        had_error = False
        processed_paths: list[str] = []
        disk_files = list(Readers.iter_files(root))
        unsupported_files = [] if only_failed else list(Readers.iter_unsupported_files(root))

        renamed_paths: set[str] = set()
        if only_new_files and not only_failed:
            with storage.transaction():
                renamed_paths = Document.reconcile_renamed_and_removed(
                    storage, source, disk_files + unsupported_files
                )
            for new_path in sorted(renamed_paths):
                processed_paths.append(new_path)
                if on_file_done is not None:
                    on_file_done(new_path)

        Document.record_unsupported(
            storage, source, [path for path in unsupported_files if str(path) not in renamed_paths]
        )

        for file_path in disk_files:
            if should_stop is not None and should_stop():
                break
            if str(file_path) in renamed_paths:
                continue

            existing = None
            if only_new_files or only_failed:
                existing = storage.get_document_index_pending_check(str(file_path))
            if only_failed:
                if existing is None or existing["status"] != "error":
                    continue
            elif (
                only_new_files
                and existing is not None
                and existing["status"] == "indexed"
                and not Document.has_content_changed(file_path, existing)
            ):
                continue

            file_type = Readers.for_path(file_path).file_type
            try:
                with storage.transaction():
                    claim = Document.upsert(storage, source.id, file_path, file_type)
            except FileNotFoundError:
                # Vanished between discovery and claiming, so there's nothing to
                # index; the next run's reconcile marks any tracked row 'removed'.
                _logger.warning("File removed before indexing, skipped: %s", file_path)
                continue
            if claim is None:
                # Already claimed by another concurrently-running index run -
                # leave it alone, that run owns finishing it.
                continue
            document_id, duplicate_source_id = claim
            processed_paths.append(str(file_path))

            if duplicate_source_id is not None:
                # Identical content already indexed under the same logical document -
                # skip OCR entirely rather than redoing the same work.
                with storage.transaction():
                    Document.mark_duplicate(storage, document_id)
                if on_file_done is not None:
                    on_file_done(str(file_path))
                continue

            process = psutil.Process()
            process.cpu_percent(interval=None)  # prime; the next call reports usage since now
            mem_before = process.memory_info().rss

            reader = Readers.for_path(file_path)
            pages, attempts_used, last_exc = Quick.run_with_retries(storage, reader, file_path)

            peak_memory_mb = max(mem_before, process.memory_info().rss) / (1024 * 1024)
            cpu_percent = process.cpu_percent(interval=None)
            succeeded = Quick.finalize_result(
                storage,
                document_id,
                file_type,
                pages,
                attempts_used,
                last_exc,
                peak_memory_mb,
                cpu_percent,
            )
            if not succeeded:
                had_error = True

            if on_file_done is not None:
                on_file_done(str(file_path))

        with storage.transaction():
            storage.update_source_scan_status(
                source.id,
                "error" if had_error else "indexed",
                datetime.now(UTC).isoformat(),
            )
        return processed_paths

    @staticmethod
    def process_file(
        storage: Storage,
        source: Source,
        file_path: Path,
        file_type: str,
        *,
        db_lock: threading.Lock,
    ) -> bool | None:
        """Index one file: upsert its row, dedupe by checksum, and OCR it if new content.

        Returns whether it succeeded (False on an OCR failure recorded as an
        error), or None if `file_path` is already claimed by another
        concurrently-running index run and was left untouched - see
        `Document.upsert`. This is `Quick.run`'s per-file body, pulled out
        separately so `Quick.run_batch` can process files interleaved across
        sources rather than one whole source at a time, and so OCR inference -
        the actual work worth parallelizing - runs without `db_lock` held; every
        sqlite read/write around it is serialized through `db_lock` since a
        single connection isn't safe for unsynchronized concurrent use.
        """
        try:
            with db_lock, storage.transaction():
                claim = Document.upsert(storage, source.id, file_path, file_type)
        except FileNotFoundError:
            # Vanished between discovery and claiming - leave it for the next
            # run's reconcile rather than aborting the batch.
            _logger.warning("File removed before indexing, skipped: %s", file_path)
            return None

        if claim is None:
            return None
        document_id, duplicate_source_id = claim

        if duplicate_source_id is not None:
            with db_lock, storage.transaction():
                Document.mark_duplicate(storage, document_id)
            return True

        process = psutil.Process()
        process.cpu_percent(interval=None)  # prime; the next call reports usage since now
        mem_before = process.memory_info().rss

        reader = Readers.for_path(file_path)
        pages, attempts_used, last_exc = Quick.run_with_retries(storage, reader, file_path)

        with db_lock:
            peak_memory_mb = max(mem_before, process.memory_info().rss) / (1024 * 1024)
            cpu_percent = process.cpu_percent(interval=None)
            return Quick.finalize_result(
                storage,
                document_id,
                file_type,
                pages,
                attempts_used,
                last_exc,
                peak_memory_mb,
                cpu_percent,
            )

    @staticmethod
    def run_auto_elastic(
        storage: Storage,
        pending: list[PendingFile],
        initial_workers: int,
        handle_one: Callable[[PendingFile], None],
        should_stop: Callable[[], bool] | None,
        on_workers_changed: Callable[[int], None] | None,
        *,
        db_lock: threading.Lock,
    ) -> None:
        """Process `pending` with a worker count re-resolved after every file.

        Spawns up to `min(IndexSettings.THREAD_WORKERS_MAX, len(pending))` worker threads up
        front - an idle one just waits (cheap), never torn down or recreated -
        but only lets `active_workers` of them (by slot index) actually pull
        work at a time. `active_workers` is recomputed via
        `Scheduler.resolve_workers` after every file finishes, from the file-type
        mix still remaining, so the active count grows or shrinks with current
        CPU/memory headroom as the run progresses rather than being fixed for
        the whole run.
        """
        max_slots = max(1, min(IndexSettings.THREAD_WORKERS_MAX, len(pending)))
        remaining_counts = Readers.new_file_type_counts()
        for item in pending:
            remaining_counts[item.file_type] += 1

        coord_lock = threading.Lock()
        next_index = 0
        in_flight = 0
        active_workers = max(1, min(initial_workers, max_slots))

        def take_next(slot: int) -> PendingFile | _Wait | None:
            nonlocal next_index, in_flight
            with coord_lock:
                # Checked in this order deliberately: once the queue is drained,
                # every slot must be able to exit - including one parked past
                # `active_workers` - rather than waiting forever for a turn that
                # active_workers shrinking (as remaining work runs low) may
                # never actually give it.
                if next_index >= len(pending):
                    return None
                if slot >= active_workers:
                    return _WAIT
                item = pending[next_index]
                # Only defer for a heavier-than-usual file when something else is
                # already running - if this slot is the only thing left, nothing
                # will ever free up the budget it's waiting on, so it must proceed
                # regardless (queue order is otherwise preserved either way: the
                # head of the queue is never skipped, just held).
                if in_flight > 0:
                    with db_lock:
                        if Scheduler.would_exceed_budget(storage, item):
                            return _WAIT
                next_index += 1
                in_flight += 1
                return item

        def report_done(file_type: str) -> None:
            nonlocal active_workers, in_flight
            changed_to: int | None = None
            with coord_lock:
                in_flight -= 1
                remaining_counts[file_type] -= 1
                if sum(remaining_counts.values()) > 0:
                    # `db_lock`, not just `coord_lock`: `Scheduler.resolve_workers`
                    # reads `storage` (the `thread_workers` setting), and every use
                    # of this connection across worker threads is serialized
                    # through `db_lock` - see `Quick.process_file`.
                    with db_lock:
                        resolved = Scheduler.resolve_workers(storage, remaining_counts)
                    new_active_workers = max(1, min(resolved, max_slots))
                    if new_active_workers != active_workers:
                        active_workers = new_active_workers
                        changed_to = new_active_workers
            if changed_to is not None and on_workers_changed is not None:
                on_workers_changed(changed_to)

        def worker_loop(slot: int) -> None:
            while True:
                if should_stop is not None and should_stop():
                    return
                item = take_next(slot)
                if item is None:
                    return
                if isinstance(item, _Wait):
                    time.sleep(Quick.IDLE_POLL_SECONDS)
                    continue
                handle_one(item)
                report_done(item.file_type)

        threads = [threading.Thread(target=worker_loop, args=(slot,)) for slot in range(max_slots)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    @staticmethod
    def run_batch(
        storage: Storage,
        sources: list[Source],
        *,
        only_failed: bool = False,
        workers: int = 1,
        on_file_start: Callable[[str], None] | None = None,
        on_file_done: Callable[[str, bool | None], None] | None = None,
        on_workers_changed: Callable[[int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        exclude_paths: Collection[str] = (),
        on_pending: Callable[[int], None] | None = None,
    ) -> list[str]:
        """Like `Quick.run`, but across every source in `sources` at once.

        Every source's pending files are flattened into a single list ordered
        by filename - `Path.name`, not the full path, and not grouped by source
        - before processing, so a run over multiple sources reads as them
        indexing in parallel rather than strictly one source at a time. This
        ordering is independent of `workers`, which separately controls how
        many files are actually OCR'd concurrently (see `Scheduler.resolve_workers`
        for how that count is chosen; 0 or 1 processes the list sequentially in
        the calling thread with no pool at all).

        `only_failed` and the per-source `only_new_files` choice (a source
        that's already been indexed only has new/changed/failed files
        reconsidered; a fresh/reactivated source has every file reprocessed)
        match `Quick.run`'s semantics exactly, just applied per source before the
        combined list is built.

        `should_stop` is checked before each file is started; once it returns
        True, no further files are started - in-flight ones still finish - and
        the rest of the list is left untouched. `on_file_start`, when given, is
        called with a file's path right before it's (re)processed; `on_file_done`
        is called with its path and whether it succeeded immediately after -
        both from whichever thread actually processed that file. `on_file_done`'s
        second argument is None instead of a bool if the file turned out to
        already be claimed by another concurrently-running index run (see
        `Document.upsert`) - that file was left untouched here and doesn't count
        as attempted/processed/failed for this run, though `on_file_done` still
        fires so a caller tracking in-flight files clears it from that list.

        When the `thread_workers` setting is 'auto', the worker count is instead
        re-resolved after every file (see `Quick.run_auto_elastic`) rather than fixed
        for the whole run at `workers` - so it keeps adapting to CPU/memory
        headroom and the shrinking pending mix as the run progresses; whenever
        that changes it, `on_workers_changed` (when given) is called with the
        new count, so a caller reporting progress can keep it current.

        `exclude_paths` leaves those files out of the list (see
        `Pending.iter_files`); `on_pending`, when given, is called once with the
        number of files the list ended up with, before any is processed.

        A source's `sources.status` is only updated once at least one of its
        files in this run's list was attempted, using the outcome of whichever
        of its files got processed before the run stopped (if it did) - a
        source with no files attempted this run is left untouched.

        Returns the paths of the files actually (re)processed, in the order
        they finished (not the processing order for `workers` > 1).
        """
        pending: list[PendingFile] = []
        for source in sources:
            only_new_files = source.status != "pending"
            renamed_paths: set[str] = set()
            unsupported_files = (
                [] if only_failed else list(Readers.iter_unsupported_files(Path(source.path)))
            )
            if only_new_files and not only_failed:
                disk_files = list(Readers.iter_files(Path(source.path)))
                with storage.transaction():
                    renamed_paths = Document.reconcile_renamed_and_removed(
                        storage, source, disk_files + unsupported_files
                    )
                for renamed_path in sorted(renamed_paths):
                    if on_file_done is not None:
                        on_file_done(renamed_path, True)
            Document.record_unsupported(
                storage,
                source,
                [path for path in unsupported_files if str(path) not in renamed_paths],
            )
            for file_path, file_type in Pending.iter_files(
                storage,
                source,
                only_new_files=only_new_files,
                only_failed=only_failed,
                exclude_paths=exclude_paths,
            ):
                pending.append(PendingFile(source, file_path, file_type))

        pending.sort(key=lambda item: (item.path.name, str(item.path)))
        if on_pending is not None:
            on_pending(len(pending))

        attempted_source_ids: set[int] = set()
        had_error_by_source: dict[int, bool] = {}
        processed_paths: list[str] = []
        state_lock = threading.Lock()
        db_lock = threading.Lock()

        def handle_one(item: PendingFile) -> None:
            path_str = str(item.path)
            if on_file_start is not None:
                on_file_start(path_str)
            succeeded = Quick.process_file(
                storage, item.source, item.path, item.file_type, db_lock=db_lock
            )
            if succeeded is not None:
                # None means the file was already claimed by another
                # concurrently-running index run and left untouched here - that
                # run's own bookkeeping covers it, so it doesn't count as
                # attempted/processed/failed for this one.
                with state_lock:
                    processed_paths.append(path_str)
                    attempted_source_ids.add(item.source.id)
                    had_error_by_source[item.source.id] = (
                        had_error_by_source.get(item.source.id, False) or not succeeded
                    )
            if on_file_done is not None:
                on_file_done(path_str, succeeded)

        if IndexSettings.get_thread_workers(storage) == IndexSettings.THREAD_WORKERS_AUTO:
            Quick.run_auto_elastic(
                storage,
                pending,
                workers,
                handle_one,
                should_stop,
                on_workers_changed,
                db_lock=db_lock,
            )
        elif workers <= 1:
            for item in pending:
                if should_stop is not None and should_stop():
                    break
                handle_one(item)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = []
                for item in pending:
                    if should_stop is not None and should_stop():
                        break
                    futures.append(executor.submit(handle_one, item))
                for future in futures:
                    future.result()

        now = datetime.now(UTC).isoformat()
        with storage.transaction():
            for source in sources:
                if source.id in attempted_source_ids:
                    status = "error" if had_error_by_source[source.id] else "indexed"
                    storage.update_source_scan_status(source.id, status, now)

        return processed_paths
