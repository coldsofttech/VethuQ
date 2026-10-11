"""The indexer: finds a source's files and reads each into pages."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from vethuq._credits import _Clock, _Credits, _PageMeter, _PageTooLarge
from vethuq._db import _Database, _Document, _DocumentIndex, _IndexRun, _Language, _Source
from vethuq._db.values import _PageSource, _PageState
from vethuq._documents import _Documents
from vethuq._errors import (
    _CreditsExhaustedError,
    _OcrModelMissingError,
    _SourceNotFoundError,
    _SourcePathError,
)
from vethuq._filetypes import _FileTypeCatalog
from vethuq._indexing.deepening import _Deepener
from vethuq._indexing.gate import _ContentGate, _Scheduler
from vethuq._indexing.remote import _Outbox, _Remote
from vethuq._indexing.runs import _Runs
from vethuq._indexing.store import _PageStore
from vethuq._languages import _Languages
from vethuq._ocr import _PageOcr, _PageResult
from vethuq._settings import _ConfidenceSettings, _IndexSettings, _OcrSettings, _TierSettings
from vethuq._sources import _Files, _Sources
from vethuq._stats import _ErrorCode, _PageFact, _Usage
from vethuq._tiers import HYBRID, LOCAL, _Router, _Tiers, _TierView
from vethuq.enums import FileStatus, IndexRunStatus
from vethuq_addon_api import (
    FileRemovedError,
    LanguageSpec,
    OcrPhaseSpec,
    PasswordProtectedError,
    UnreadableFileError,
)


@dataclass
class _Plan:
    """What one file needs, worked out when it is claimed."""

    row_id: int
    path: str
    language: LanguageSpec
    language_id: int
    manual: bool
    source_id: int
    file_type: str


class _Indexer:
    _logger = logging.getLogger("vethuq.indexing")
    # Seconds to wait before trying a failed file again (the n-th time: n * RETRY_DELAY).
    RETRY_DELAY = 0.5

    def __init__(
        self,
        database: _Database,
        file_types: _FileTypeCatalog,
        languages: Callable[[], list[LanguageSpec]],
        tiers: _Tiers,
        credits: _Credits,
        after_pages: Callable[[], object] | None = None,
        phases: Callable[[], list[OcrPhaseSpec]] = list,
    ) -> None:
        self._after_pages = after_pages
        self.database = database
        self.file_types = file_types
        self.languages = languages
        self.tiers = tiers
        self._tier: _TierView | None = None
        self._remote_tier: _TierView | None = None  # where pages that are sent away go
        self._router: _Router | None = None  # hybrid only: which pages are sent
        self.credits = credits
        self._run_id: int | None = None
        self._paused = threading.Event()
        self._outbox: _Outbox | None = None
        self.remote = _Remote(database, tiers, credits, self._language_id, self._file_type_id)
        self.gate = _ContentGate()
        self.deepener = _Deepener(
            database, file_types, tiers, credits, self.remote, phases, languages
        )
        self.remote.deepener = self.deepener

    # ----- the target -------------------------------------------------------------------------

    def _resolve(
        self, session: Session, target: int | str | Path | None
    ) -> tuple[list[_Source], str | None]:
        """The sources to index and, for a single file, its path."""
        if target is None:
            return _Sources.list_sources(session), None
        if isinstance(target, bool) or not isinstance(target, int | str | Path):
            raise TypeError("A target is a source id (int) or a path (str or Path).")
        if isinstance(target, int):
            return [_Sources.get(session, target)], None
        resolved = Path(target).expanduser().resolve()
        source = _Sources.find_by_path(session, str(resolved))
        if source is not None and source.is_active:
            return [source], None
        for candidate in _Sources.list_sources(session):
            inside = resolved.is_relative_to(Path(candidate.path))
            known = _Documents.find(session, str(resolved)) is not None
            if inside and (resolved.is_file() or known):
                return [candidate], str(resolved)
        raise _SourceNotFoundError(
            f"No active source matches or holds: {resolved}",
            "Use sources.list() to see the registered sources.",
        )

    # ----- discovery --------------------------------------------------------------------------

    def _discover(
        self, session: Session, sources: list[_Source], only_file: str | None
    ) -> list[int]:
        """Bring the document index up to date with the disk; return the ids of the rows to do."""
        todo: list[int] = []
        for source in sources:
            try:
                entries = _Files.list(source.path)
            except _SourcePathError:
                if len(sources) == 1:
                    raise
                self._logger.warning("Source %d is missing from disk: %s", source.id, source.path)
                entries = []
            if only_file is not None:
                entries = [e for e in entries if e.path == only_file]
            seen = set()
            for entry in entries:
                seen.add(entry.path)
                if not self.file_types.is_supported(entry.path):
                    continue
                _Documents.register(
                    session, source, entry.path, entry.size_bytes, entry.modified_at, refresh=False
                )
            for row in _Documents.rows(session, source.id):
                if only_file is not None and row.file_path != only_file:
                    continue
                if row.file_path not in seen and row.status not in (
                    FileStatus.REMOVED,
                    FileStatus.UNSUPPORTED,
                ):
                    _Documents.mark_removed(session, row)
                elif row.status in (
                    FileStatus.PENDING,
                    FileStatus.MODIFIED,
                    FileStatus.ERROR,
                ) and self.file_types.is_supported(row.file_path):
                    todo.append(row.id)
            source.last_scanned_at = _Runs._now()
            session.flush()
            _Documents.refresh_source(session, source.id)
        return todo

    def _settle(self, row_ids: list[int], seconds: float) -> list[int]:
        """Wait once, then drop the files that changed meanwhile for the next run (they're
        still being written), and note the ones that went."""
        if seconds <= 0 or not row_ids:
            return row_ids
        with self.database.session() as session:
            before = {
                r.id: (r.file_path, r.size_bytes, r.modified_at)
                for r in session.scalars(
                    select(_DocumentIndex).where(_DocumentIndex.id.in_(row_ids))
                )
            }
        time.sleep(seconds)
        stable: list[int] = []
        with self.database.session() as session:
            for row_id in row_ids:
                path, size, modified = before[row_id]
                entry = _Files.entry(Path(path), Path(path).parent)
                row = session.get(_DocumentIndex, row_id)
                if entry is None:
                    _Documents.mark_removed(session, row)
                elif (entry.size_bytes, entry.modified_at) == (size, modified):
                    stable.append(row_id)
                else:
                    source = session.get(_Source, row.source_id)
                    _Documents.register(session, source, path, entry.size_bytes, entry.modified_at)
                    stable.append(row_id)  # read it as it is now
        return stable

    # ----- one file ---------------------------------------------------------------------------

    @staticmethod
    def _hash(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _plan(self, session: Session, row_id: int) -> _Plan | None:
        row = session.get(_DocumentIndex, row_id)
        if row is None or row.status is FileStatus.REMOVED:
            return None
        if not Path(row.file_path).is_file():
            _Documents.mark_removed(session, row)
            return None
        source = session.get(_Source, row.source_id)
        specs = self.languages()
        manual = bool(source.language_codes)
        code = (source.language_codes if manual else _Languages.default_ids(session, specs))[0]
        language = next((s for s in specs if s.id == code), None)
        if language is None:
            _Documents.start(session, row)
            _Documents.fail(
                session, row, f"The language {code!r} isn't installed.", _ErrorCode.LANGUAGE
            )
            return None
        language_id = session.scalars(select(_Language.id).where(_Language.language == code)).one()
        _Documents.start(session, row)
        spec = self.file_types.for_path(row.file_path)
        return _Plan(
            row.id,
            row.file_path,
            language,
            language_id,
            manual,
            row.source_id,
            spec.id if spec else "",
        )

    def _language_id(self, session: Session, row: _DocumentIndex) -> int | None:
        """The id of the language a file is read in (its source's first, else the default)."""
        source = session.get(_Source, row.source_id)
        if source is None:
            return None
        specs = self.languages()
        codes = source.language_codes or _Languages.default_ids(session, specs)
        return session.scalar(select(_Language.id).where(_Language.language == codes[0]))

    def _file_type_id(self, path: str) -> str:
        spec = self.file_types.for_path(path)
        return spec.id if spec else ""

    def _skip(self, number: int, pages: dict, read: set[int], staged: set[int]) -> bool:
        """Whether a page needs nothing more in this pass: it was read in this language, its
        images are already staged or away, or it has no OCR to do."""
        if number in read or number in staged:
            return True
        page = pages.get(number)
        return (
            page is not None
            and page.source is _PageSource.NATIVE
            and page.status is _PageState.DONE
        )

    def _attempt(self, plan: _Plan) -> str:
        """Read one file once. Every page is paid for as it is read and saved at once, so a file
        that stops part way (no credits, a crash, a failure) keeps its pages and the next
        attempt carries on after them. Returns "done", or "staged" when pages are away."""
        sha256 = self._hash(plan.path)
        file_type = self.file_types.for_path(plan.path)
        if file_type is None:
            raise UnreadableFileError(plan.path, "no add-on reads this kind of file")
        with self.gate.hold(sha256):
            with self.database.session() as session:
                row = session.get(_DocumentIndex, plan.row_id)
                document = _Documents.attach(session, row, sha256)
                document_id = document.id
                if _PageStore.covers(session, document_id, plan.language_id):
                    _Documents.finish(session, row, sha256)
                    return "done"
                additional = _PageStore.read_before(session, document_id, plan.language_id)
                _PageStore.begin_pass(session, document_id, plan.language_id, manual=plan.manual)
                pages = _PageStore.pages(session, document_id)
                read = _PageStore.read_in(session, document_id, plan.language_id)
                staged = self.remote.staged(session, document_id, plan.language_id)
            meters: dict[str, _PageMeter] = {}

            def meter_for(wallet: str) -> _PageMeter:
                if wallet not in meters:
                    meters[wallet] = _PageMeter(
                        self.credits,
                        source_id=plan.source_id,
                        run_id=self._run_id,
                        label=plan.path,
                        language=plan.language.id,
                        additional_language=additional,
                        wallet=wallet,
                    )
                return meters[wallet]

            prefix = f"d{document_id}.l{plan.language_id}."
            try:
                for number, page in _PageOcr.pages(
                    file_type.reader, Path(plan.path), self.file_types.reader_for
                ):
                    if self._skip(number, pages, read, staged):
                        continue
                    result = self._read(number, page, plan, meter_for, prefix)
                    self._save_page(plan, document_id, result)
                    for meter in meters.values():
                        meter.forget()
            except BaseException:
                for meter in meters.values():
                    meter.refund_all()
                raise
            with self.database.session() as session:
                row = session.get(_DocumentIndex, plan.row_id)
                if _PageStore.waiting(session, document_id) or self.remote.staged(
                    session, document_id, plan.language_id
                ):
                    return "staged"
                _PageStore.finish_pass(session, document_id, plan.language_id)
                _Documents.finish(session, row, sha256)
            return "done"

    def _read(self, number, page, plan: _Plan, meter_for, prefix: str) -> _PageResult:
        """Read one page with the tier that suits it. A hybrid run keeps a page here unless the
        router sends it away; a page that can't be paid for on the remote tier is read here."""
        tier = self._tier
        if tier is None:
            return _PageOcr.read_page(
                number, page, None, plan.language, meter_for(LOCAL), key_prefix=prefix
            )
        if tier.id != HYBRID:
            return _PageOcr.read_page(
                number,
                page,
                tier.executor,
                plan.language,
                meter_for(tier.wallet),
                key_prefix=prefix,
            )
        local, remote = self.tiers.hybrid_parts()
        away = False
        if self._router is not None and _PageOcr.needs_ocr(page):
            try:
                factor = (
                    meter_for(local.wallet).pricing().size_factor(page.width_pt, page.height_pt)
                )
            except _PageTooLarge:
                factor = 0.0  # reading it fails the same way anywhere
            away = self._router.remote(factor)
        if away:
            try:
                return _PageOcr.read_page(
                    number, page, remote.executor, plan.language, meter_for(remote.wallet),
                    key_prefix=prefix,
                )  # fmt: skip
            except _CreditsExhaustedError:
                self._logger.info("GitHub credits are used up; page %d is read here", number)
        return _PageOcr.read_page(
            number, page, local.executor, plan.language, meter_for(local.wallet), key_prefix=prefix
        )

    def _save_page(self, plan: _Plan, document_id: int, result: _PageResult) -> None:
        """Save one page the moment it is read: the page, what it cost, and the run's counts. A
        page whose OCR is away is saved waiting, with its images staged to be sent."""
        ids: list[int] = []
        with self.database.session() as session:
            _PageStore.save_page(session, document_id, result, plan.language_id, plan.file_type)
            if result.pending:
                ids = self.remote.stage(
                    session, document_id, plan.language_id, result, self._run_id,
                    self._remote_tier.wallet if self._remote_tier else "local",
                )  # fmt: skip
            else:
                fact = _PageFact(
                    page_source=result.source.value,
                    phase="quick" if result.quick else "",
                    engine=result.quick.engine if result.quick else "",
                    size_bucket=self.credits_bucket(result.size_factor),
                    confidence=result.confidence,
                    duration_ms=result.quick.duration_ms if result.quick else 0,
                    credits_milli=result.credits_milli,
                    passes=1 if result.quick else 0,
                )
                _Usage.record_pages(
                    session,
                    _Clock.today(session).isoformat(),
                    plan.source_id,
                    plan.file_type,
                    plan.language.id,
                    [fact],
                    _ConfidenceSettings.get_bands(session),
                )
                if self._run_id is not None:  # one statement: workers can't lose each other's count
                    session.execute(
                        update(_IndexRun)
                        .where(_IndexRun.id == self._run_id)
                        .values(processed_pages=_IndexRun.processed_pages + 1)
                    )
        if result.pending and self._outbox is not None:
            self._outbox.add(list(result.requests), ids)

    @staticmethod
    def credits_bucket(factor: float) -> str:
        from vethuq._credits import _Pricing  # noqa: PLC0415

        return _Pricing.bucket(factor)

    @staticmethod
    def _code(exc: BaseException) -> str:
        if isinstance(exc, _PageTooLarge):
            return _ErrorCode.PAGE_TOO_LARGE
        if isinstance(exc, _OcrModelMissingError):
            return _ErrorCode.OCR_UNAVAILABLE
        if isinstance(exc, PasswordProtectedError):
            return _ErrorCode.PASSWORD
        if isinstance(exc, UnreadableFileError):
            return _ErrorCode.CORRUPT if "damaged" in str(exc) else _ErrorCode.UNREADABLE
        return _ErrorCode.OTHER

    def _failed(self, plan: _Plan, row_id: int, message: str, code: str, *, unsupported=False):
        with self.database.session() as session:
            row = session.get(_DocumentIndex, row_id)
            if unsupported:
                _Documents.mark_unsupported(session, row, message, code)
            else:
                _Documents.fail(session, row, message, code)
            if row.document_id is not None:
                _PageStore.fail_pass(session, row.document_id, plan.language_id, message)
            _Usage.record_failure(
                session, _Clock.today(session).isoformat(), plan.source_id, plan.file_type, code
            )

    def _process(self, row_id: int, retries: int) -> str:
        """Index one file, trying again if it fails. Returns "ok", "failed" or "paused" (the
        credits ran out, so the file is waiting again)."""
        with self.database.session() as session:
            plan = self._plan(session, row_id)
        if plan is None:
            with self.database.session() as session:
                row = session.get(_DocumentIndex, row_id)
                return "ok" if row is not None and row.status is FileStatus.REMOVED else "failed"
        message, code = "", _ErrorCode.OTHER
        for attempt in range(retries + 1):
            try:
                return "ok" if self._attempt(plan) == "done" else "staged"
            except _CreditsExhaustedError:
                self._paused.set()
                with self.database.session() as session:
                    _Documents.put_back(session, session.get(_DocumentIndex, row_id))
                return "paused"
            except (FileNotFoundError, FileRemovedError):
                with self.database.session() as session:
                    _Documents.mark_removed(session, session.get(_DocumentIndex, row_id))
                return "ok"
            except PasswordProtectedError as exc:
                self._failed(plan, row_id, str(exc), _ErrorCode.PASSWORD, unsupported=True)
                return "ok"
            except (UnreadableFileError, _OcrModelMissingError, _PageTooLarge) as exc:
                message, code = str(exc), self._code(exc)
                break  # trying again won't change it
            except Exception as exc:  # noqa: BLE001 - one file never stops the run
                message = f"{type(exc).__name__}: {exc}" if not str(exc) else str(exc)
                self._logger.warning("Indexing %s failed (try %d)", plan.path, attempt + 1)
                if attempt < retries:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
        self._failed(plan, row_id, message, code)
        return "failed"

    # ----- estimating -------------------------------------------------------------------------

    def estimate(self, target: int | str | Path | None) -> tuple[int, int, int, int]:
        """(files, pages, OCR pages, milli-credits) indexing `target` would take now."""
        todo: list[tuple[str, str | None, bool]] = []
        with self.database.session() as session:
            sources, only_file = self._resolve(session, target)
            pricing = self.credits.pricing(session)
            specs = self.languages()
            for source in sources:
                try:
                    entries = _Files.list(source.path)
                except _SourcePathError:
                    continue
                rows = {r.file_path: r for r in _Documents.rows(session, source.id)}
                code = (source.language_codes or _Languages.default_ids(session, specs))[0]
                for entry in entries:
                    if only_file is not None and entry.path != only_file:
                        continue
                    spec = self.file_types.for_path(entry.path)
                    status = _Sources.file_status(rows.get(entry.path), entry, spec is not None)
                    if spec is not None and status in (
                        FileStatus.PENDING,
                        FileStatus.MODIFIED,
                        FileStatus.ERROR,
                        FileStatus.PROCESSING,
                    ):
                        todo.append((entry.path, code, spec is not None))
            language_ids = dict(session.execute(select(_Language.language, _Language.id)).all())
        files = pages = ocr_pages = cost = 0
        for path, code, _ in todo:
            try:
                sha256 = self._hash(path)
            except OSError:
                continue
            additional = False
            with self.database.session() as session:
                document = session.scalars(
                    select(_Document).where(_Document.sha256 == sha256)
                ).first()
                if document is not None:
                    language_id = language_ids.get(code or "")
                    if language_id is None or _PageStore.covers(session, document.id, language_id):
                        continue
                    additional = True
            file_type = self.file_types.for_path(path)
            try:
                found = list(
                    _PageOcr.pages(file_type.reader, Path(path), self.file_types.reader_for, False)
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("Couldn't read %s to estimate it", path)
                continue  # an unreadable file costs nothing
            files += 1
            for _number, page in found:
                pages += 1
                if not _PageOcr.needs_ocr(page):
                    continue
                has_text = _PageOcr.has_text(page.native_text.strip())
                try:
                    factor = pricing.size_factor(page.width_pt, page.height_pt)
                except _PageTooLarge:
                    continue
                ocr_pages += 1
                cost += pricing.cost_milli(
                    factor,
                    additional_language=additional,
                    covered=_PageOcr.covered(page) if has_text else 1.0,
                )
        return files, pages, ocr_pages, cost

    # ----- a run ------------------------------------------------------------------------------

    def run(
        self,
        target: int | str | Path | None,
        workers: int | str | None,
        tier: str | None = None,
        wait: bool | None = None,
        timeout: float | None = None,
    ) -> int:
        """Index `target` (a source, a file in one, or every source) and return the run's id.

        Work sent to a remote tier is collected at the start (jobs from earlier runs) and at the
        end. With `wait`, the end waits for the run's own jobs, up to `timeout` minutes."""
        with self.database.session() as session:
            sources, only_file = self._resolve(session, target)
            count = _Scheduler.resolve(
                workers if workers is None else _IndexSettings.parse_workers(workers),
                _IndexSettings.get_workers(session),
            )
            retries = _IndexSettings.get_retry_attempts(session)
            seconds = _IndexSettings.get_stability_check_seconds(session)
            source_id = sources[0].id if target is not None else None
            _Languages.ensure_rows(session, self.languages())  # once, before the workers start
            view = self.tiers.resolve(tier, _TierSettings.get_default(session))
            remote_tier, router = None, None
            if view.id == HYBRID:
                _local, remote_tier = self.tiers.hybrid_parts()
                router = _Router(
                    _TierSettings.get_min_size_factor(session),
                    tuple(_TierSettings.get_phases(session)),
                )
                self.credits.sync(session, remote_tier.wallet)
            elif view.asynchronous:
                remote_tier = view
            self.credits.sync(session, view.wallet)  # today's allowance, before the workers start
            run = _Runs.begin(session, source_id, only_file, count, view.id)
            run_id = run.id
            self.remote.recover(session)
            wait_minutes = timeout or _TierSettings.get_wait_timeout_minutes(session)
        self._run_id = run_id
        self._tier, self._remote_tier, self._router = view, remote_tier, router
        self._outbox = _Outbox(self.remote, remote_tier.id, run_id) if remote_tier else None
        self._paused.clear()
        counts = {"processed": 0, "failed": 0}
        lock = threading.Lock()
        try:
            self.remote.collect()  # jobs left by earlier runs that have finished since
            with self.database.session() as session:
                todo = self._discover(
                    session, [session.get(_Source, s.id) for s in sources], only_file
                )
            todo = self._settle(todo, seconds)
            with self.database.session() as session:
                session.get(_IndexRun, run_id).total_files = len(todo)
            attempted = set(todo)

            def work(row_id: int) -> None:
                if self._paused.is_set():
                    return
                outcome = self._process(row_id, retries)
                if outcome in ("paused", "staged"):
                    return  # paused: waiting for credits; staged: the pages are away
                with lock:
                    counts["processed"] += 1
                    counts["failed"] += 0 if outcome == "ok" else 1
                    snapshot = dict(counts)
                with self.database.session() as session:
                    record = session.get(_IndexRun, run_id)
                    record.processed_files = max(record.processed_files, snapshot["processed"])
                    record.failed_files = max(record.failed_files, snapshot["failed"])

            def quick(rows: list[int]) -> None:
                """The quick phase for these files: the first read of each."""
                if count <= 0:
                    for row_id in rows:
                        work(row_id)
                else:
                    with ThreadPoolExecutor(
                        max_workers=count, thread_name_prefix="vethuq-index"
                    ) as pool:
                        for future in [pool.submit(work, row_id) for row_id in rows]:
                            future.result()

            quick(todo)
            self._deepen(run_id, sources, only_file, source_id, count, seconds, attempted, quick)
            if self._outbox is not None:
                self._outbox.flush()
            self._await_remote(run_id, wait, wait_minutes)
            self._refresh_search()
            if self._paused.is_set():
                self._finish(
                    run_id,
                    IndexRunStatus.WAITING_CREDITS,
                    "Out of credits; they reset at 00:00 UTC. Run again then.",
                    counts,
                )
            elif self._remote_open(run_id):
                self._finish(
                    run_id,
                    IndexRunStatus.WAITING_REMOTE,
                    "Pages are away on the remote tier; run again, or collect, later.",
                    counts,
                )
            else:
                self._finish(run_id, IndexRunStatus.COMPLETED, None, counts)
        except KeyboardInterrupt:
            self._finish(run_id, IndexRunStatus.STOPPED, "Interrupted.", counts)
            raise
        except BaseException as exc:
            self._finish(run_id, IndexRunStatus.FAILED, str(exc) or type(exc).__name__, counts)
            raise
        finally:
            _Runs.end(run_id)
            self._run_id = None
            self._tier = self._remote_tier = self._router = None
            self._outbox = None
        return run_id

    # ----- the deeper phases ------------------------------------------------------------------

    # How often, in seconds, a run in its deeper phases looks for new or changed files: they go
    # back to the front of the queue and get their quick read first.
    QUICK_CHECK_SECONDS = 5.0

    def _fresh(
        self,
        sources: list[_Source],
        only_file: str | None,
        attempted: set[int],
        seconds: float,
        run_id: int,
    ) -> list[int]:
        """The files that need their quick read and haven't had it in this run: new ones, and
        ones that changed."""
        with self.database.session() as session:
            todo = self._discover(session, [session.get(_Source, s.id) for s in sources], only_file)
        fresh = self._settle([row for row in todo if row not in attempted], seconds)
        if fresh:
            attempted.update(fresh)
            with self.database.session() as session:
                session.get(_IndexRun, run_id).total_files += len(fresh)
        return fresh

    def _deepen(
        self,
        run_id: int,
        sources: list[_Source],
        only_file: str | None,
        source_id: int | None,
        count: int,
        seconds: float,
        attempted: set[int],
        quick: Callable[[list[int]], None],
    ) -> None:
        """Quick is done: read the pages again for each deeper phase the engine setting reaches,
        moderate before deep. The first priority stays quick: every few seconds the run looks for
        new or changed files and, if there are any, reads them (quick) before going on."""
        with self.database.session() as session:
            engine = _OcrSettings.get_engine(session)
        if _PageOcr.order(engine) <= _PageOcr.order("quick"):
            return
        for name in self.deepener.missing(engine):
            self._logger.warning(
                "The %s OCR phase is not installed, so it is skipped (pip install "
                "vethuq-addon-ocr-%s).", name, name,
            )  # fmt: skip
        phases = self.deepener.deeper(engine)
        if not phases:
            return
        tried: set[tuple[int, int, str]] = set()
        chunk = max(count, 1) * 4
        last_check = time.monotonic()
        while not self._paused.is_set():
            if time.monotonic() - last_check >= self.QUICK_CHECK_SECONDS:
                last_check = time.monotonic()
                fresh = self._fresh(sources, only_file, attempted, seconds, run_id)
                if fresh:
                    quick(fresh)
                    continue
            batch: list[tuple] = []
            for spec in phases:  # the lowest phase with pages left goes first
                with self.database.session() as session:
                    units = self.deepener.units(
                        session, spec.id, (source_id, only_file), tried, chunk
                    )
                if units:
                    batch = [(spec, unit) for unit in units]
                    break
            if not batch:
                break
            tried.update((unit.page_id, unit.language_id, spec.id) for spec, unit in batch)
            if count <= 0:
                for spec, unit in batch:
                    self._deepen_one(run_id, spec, unit)
            else:
                with ThreadPoolExecutor(
                    max_workers=count, thread_name_prefix="vethuq-deepen"
                ) as pool:
                    for future in [
                        pool.submit(self._deepen_one, run_id, spec, unit) for spec, unit in batch
                    ]:
                        future.result()

    def _deepen_one(self, run_id: int, spec, unit) -> None:
        """One page, one phase. A page that can't be read now is left for the next run."""
        if self._paused.is_set():
            return
        try:
            self.deepener.read(
                unit, spec, run_id, self._tier, self._remote_tier, self._router, self._outbox,
                self._paused.is_set,
            )  # fmt: skip
        except _CreditsExhaustedError:
            self._paused.set()
        except (FileNotFoundError, FileRemovedError, UnreadableFileError, _PageTooLarge) as exc:
            self._logger.warning("Couldn't read %s again for %s: %s", unit.path, spec.id, exc)
        except _OcrModelMissingError as exc:
            self._logger.warning("The %s OCR phase can't run: %s", spec.id, exc)
        except Exception:  # noqa: BLE001 - one page never stops the run
            self._logger.warning(
                "Reading %s page %d again for %s failed", unit.path, unit.page_number, spec.id,
                exc_info=True,
            )  # fmt: skip

    # ----- remote work ------------------------------------------------------------------------

    POLL_SECONDS = 5.0

    def _remote_open(self, run_id: int) -> bool:
        with self.database.session() as session:
            return bool(self.remote.open_jobs(session, run_id))

    def _await_remote(self, run_id: int, wait: bool | None, minutes: float) -> None:
        """Collect what has come back; with `wait`, keep asking until this run's jobs are done or
        the time is up."""
        self.remote.collect()
        if not wait:
            return
        deadline = time.monotonic() + minutes * 60
        while self._remote_open(run_id) and time.monotonic() < deadline:
            time.sleep(min(self.POLL_SECONDS, max(deadline - time.monotonic(), 0)))
            self.remote.collect()

    def wait_minutes(self) -> float:
        """How long, in minutes, remote jobs are waited for when the caller gives no time."""
        with self.database.session() as session:
            return _TierSettings.get_wait_timeout_minutes(session)

    def collect(
        self, run_id: int | None = None, wait: bool = False, timeout: float | None = None
    ) -> list[int]:
        """Collect the remote jobs that have finished (of a run, or all). With `wait`, keep asking
        until none is open or `timeout` minutes pass. Returns the ids of the jobs that ended."""
        with self.database.session() as session:
            minutes = timeout or _TierSettings.get_wait_timeout_minutes(session)
        ended = self.remote.collect(run_id)
        deadline = time.monotonic() + minutes * 60
        while wait:
            with self.database.session() as session:
                if not self.remote.open_jobs(session, run_id) or time.monotonic() >= deadline:
                    break
            time.sleep(min(self.POLL_SECONDS, max(deadline - time.monotonic(), 0)))
            ended += self.remote.collect(run_id)
        self._refresh_search()
        return ended

    def _refresh_search(self) -> None:
        """Bring the search index up to date with the pages just saved (best effort: a search
        does the same before it runs)."""
        if self._after_pages is None:
            return
        try:
            self._after_pages()
        except Exception:  # noqa: BLE001 - the index is rebuilt on demand
            self._logger.warning("Couldn't update the search index", exc_info=True)

    def _finish(self, run_id: int, status: IndexRunStatus, error: str | None, counts: dict) -> None:
        with self.database.session() as session:
            record = session.get(_IndexRun, run_id)
            record.status, record.error = status, error
            record.completed_at = _Runs._now()
            record.processed_files = max(record.processed_files, counts["processed"])
            record.failed_files = max(record.failed_files, counts["failed"])
            for row in _Runs.stale_processing(session):
                row.status = FileStatus.PENDING
            session.flush()
            for source in session.scalars(select(_Source)):
                _Documents.refresh_source(session, source.id)
