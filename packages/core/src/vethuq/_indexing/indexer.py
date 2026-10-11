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

from sqlalchemy import select
from sqlalchemy.orm import Session

from vethuq._db import _Database, _Document, _DocumentIndex, _IndexRun, _Language, _Source
from vethuq._db.values import _PageSource
from vethuq._documents import _Documents
from vethuq._errors import _OcrModelMissingError, _SourceNotFoundError, _SourcePathError
from vethuq._filetypes import _FileTypeCatalog
from vethuq._indexing.gate import _ContentGate, _Scheduler
from vethuq._indexing.runs import _Runs
from vethuq._indexing.store import _PageStore
from vethuq._languages import _Languages
from vethuq._ocr import _Ocr, _PageOcr, _PageResult
from vethuq._settings import _IndexSettings
from vethuq._sources import _Files, _Sources
from vethuq.enums import FileStatus, IndexRunStatus
from vethuq_addon_api import (
    FileRemovedError,
    LanguageSpec,
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


class _Indexer:
    _logger = logging.getLogger("vethuq.indexing")
    # Seconds to wait before trying a failed file again (the n-th time: n * RETRY_DELAY).
    RETRY_DELAY = 0.5

    def __init__(
        self,
        database: _Database,
        file_types: _FileTypeCatalog,
        languages: Callable[[], list[LanguageSpec]],
        ocr: _Ocr,
    ) -> None:
        self.database = database
        self.file_types = file_types
        self.languages = languages
        self.ocr = ocr
        self.gate = _ContentGate()

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
                    FileStatus.PROCESSING,
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
            _Documents.fail(session, row, f"The language {code!r} isn't installed.")
            return None
        language_id = session.scalars(select(_Language.id).where(_Language.language == code)).one()
        _Documents.start(session, row)
        return _Plan(row.id, row.file_path, language, language_id, manual)

    def _read(self, plan: _Plan, only: dict[int, _PageSource] | None) -> list[_PageResult]:
        file_type = self.file_types.for_path(plan.path)
        if file_type is None:
            raise UnreadableFileError(plan.path, "no add-on reads this kind of file")
        results: list[_PageResult] = []
        engine = None

        def engine_for():
            nonlocal engine
            if engine is None:
                engine = self.ocr.engine(plan.language)[0]
            return engine

        for number, page in _PageOcr.pages(file_type.reader, Path(plan.path)):
            if only is not None and only.get(number, _PageSource.NATIVE) is _PageSource.NATIVE:
                continue
            results.append(_PageOcr.read_page(number, page, engine_for))
        return results

    def _attempt(self, plan: _Plan) -> None:
        """Read one file once, and record it."""
        started = _Runs._now()
        sha256 = self._hash(plan.path)
        with self.gate.hold(sha256):
            only = None
            with self.database.session() as session:
                row = session.get(_DocumentIndex, plan.row_id)
                document = session.scalars(
                    select(_Document).where(_Document.sha256 == sha256)
                ).first()
                if document is not None:
                    if _PageStore.covers(session, document.id, plan.language_id):
                        _Documents.finish(session, row, sha256)
                        return
                    only = _PageStore.sources(session, document.id)
            results = self._read(plan, only)
            with self.database.session() as session:
                row = session.get(_DocumentIndex, plan.row_id)
                document = _Documents.finish(session, row, sha256)
                if only is None:
                    _PageStore.replace(session, document.id, results, plan.language_id)
                else:
                    _PageStore.merge(session, document.id, results, plan.language_id)
                confidences = [r.confidence for r in results]
                _PageStore.mark_language(
                    session,
                    document.id,
                    plan.language_id,
                    manual=plan.manual,
                    confidence=sum(confidences) / len(confidences) if confidences else None,
                    started_at=started,
                )

    def _process(self, row_id: int, retries: int) -> bool:
        """Index one file, trying again if it fails. Returns whether it succeeded."""
        with self.database.session() as session:
            plan = self._plan(session, row_id)
        if plan is None:
            with self.database.session() as session:
                row = session.get(_DocumentIndex, row_id)
                return row is not None and row.status is FileStatus.REMOVED
        message = ""
        for attempt in range(retries + 1):
            try:
                self._attempt(plan)
                return True
            except FileNotFoundError:
                with self.database.session() as session:
                    _Documents.mark_removed(session, session.get(_DocumentIndex, row_id))
                return True
            except FileRemovedError:
                with self.database.session() as session:
                    _Documents.mark_removed(session, session.get(_DocumentIndex, row_id))
                return True
            except PasswordProtectedError as exc:
                with self.database.session() as session:
                    _Documents.mark_unsupported(
                        session, session.get(_DocumentIndex, row_id), str(exc)
                    )
                return True
            except (UnreadableFileError, _OcrModelMissingError) as exc:
                message = str(exc)
                break  # trying again won't change it
            except Exception as exc:  # noqa: BLE001 - one file never stops the run
                message = f"{type(exc).__name__}: {exc}" if not str(exc) else str(exc)
                self._logger.warning("Indexing %s failed (try %d)", plan.path, attempt + 1)
                if attempt < retries:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
        with self.database.session() as session:
            _Documents.fail(session, session.get(_DocumentIndex, row_id), message)
        return False

    # ----- a run ------------------------------------------------------------------------------

    def run(self, target: int | str | Path | None, workers: int | str | None) -> int:
        """Index `target` (a source, a file in one, or every source) and return the run's id."""
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
            run = _Runs.begin(session, source_id, only_file, count)
            run_id = run.id
        counts = {"processed": 0, "failed": 0}
        lock = threading.Lock()
        try:
            with self.database.session() as session:
                todo = self._discover(
                    session, [session.get(_Source, s.id) for s in sources], only_file
                )
            todo = self._settle(todo, seconds)
            with self.database.session() as session:
                session.get(_IndexRun, run_id).total_files = len(todo)

            def work(row_id: int) -> None:
                ok = self._process(row_id, retries)
                with lock:
                    counts["processed"] += 1
                    counts["failed"] += 0 if ok else 1
                    snapshot = dict(counts)
                with self.database.session() as session:
                    record = session.get(_IndexRun, run_id)
                    record.processed_files = max(record.processed_files, snapshot["processed"])
                    record.failed_files = max(record.failed_files, snapshot["failed"])

            if count <= 0:
                for row_id in todo:
                    work(row_id)
            else:
                with ThreadPoolExecutor(
                    max_workers=count, thread_name_prefix="vethuq-index"
                ) as pool:
                    for future in [pool.submit(work, row_id) for row_id in todo]:
                        future.result()
            self._finish(run_id, IndexRunStatus.COMPLETED, None, counts)
        except KeyboardInterrupt:
            self._finish(run_id, IndexRunStatus.STOPPED, "Interrupted.", counts)
            raise
        except BaseException as exc:
            self._finish(run_id, IndexRunStatus.FAILED, str(exc) or type(exc).__name__, counts)
            raise
        finally:
            _Runs.end(run_id)
        return run_id

    def _finish(self, run_id: int, status: IndexRunStatus, error: str | None, counts: dict) -> None:
        with self.database.session() as session:
            record = session.get(_IndexRun, run_id)
            record.status, record.error = status, error
            record.completed_at = _Runs._now()
            record.processed_files = max(record.processed_files, counts["processed"])
            record.failed_files = max(record.failed_files, counts["failed"])
            for row in session.scalars(
                select(_DocumentIndex).where(_DocumentIndex.status == FileStatus.PROCESSING)
            ):
                row.status = FileStatus.PENDING
            session.flush()
            for source in session.scalars(select(_Source)):
                _Documents.refresh_source(session, source.id)
