"""The queued language passes: a file read again in the next candidate language.

After the first language has read a file and been doubted (`_LanguagePlan.settle`), the other
candidates wait in `document_languages` as pending passes, English first and the rest in order.
Once every file has had its first read, `_Passes` works through them: it reads each page that
needed OCR again in the pass's language, upright, and adds the lines that language read believably
to what the page already says, so a page in two languages ends up with both. Each page is saved as
soon as it is read; the pass is done when every page that needed OCR has been read in the language.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from vethuq._credits import _PageMeter
from vethuq._db import (
    _DocumentLanguage,
    _Language,
    _PdfPage,
    _PdfPageQuick,
    _RemoteJobPage,
)
from vethuq._db.values import _JobPageState, _PageSource, _PageState, _PassStatus
from vethuq._errors import _OcrModelMissingError
from vethuq._indexing.deepening import _Deepener, _Merge
from vethuq._indexing.store import _PageStore
from vethuq._ocr import _LanguageDetector, _PageOcr
from vethuq._tiers import HYBRID, _Router, _TierView
from vethuq_addon_api import LanguageSpec, OcrRequest, OcrResult

_logger = logging.getLogger("vethuq.indexing")


@dataclass(frozen=True)
class _PassUnit:
    """A file waiting to be read in one more language."""

    document_id: int
    language_id: int
    language_code: str
    position: int
    path: str
    source_id: int
    file_type: str

    @property
    def key(self) -> tuple[int, int]:
        return self.document_id, self.language_id


class _Passes:
    PHASE = "language"  # how a pass's images are told apart from a phase's, in a remote job

    def __init__(self, deepener: _Deepener) -> None:
        self.deepener = deepener
        self.database = deepener.database
        self.file_types = deepener.file_types
        self.tiers = deepener.tiers
        self.credits = deepener.credits
        self.languages = deepener.languages

    # ----- which files -------------------------------------------------------------------------

    def units(
        self,
        session: Session,
        scope: tuple[int | None, str | None],
        skip: set[tuple[int, int]],
        limit: int,
    ) -> list[_PassUnit]:
        """The next pending pass of each file, in queue order: every file gets its second
        language before any gets its third."""
        source_id, only_file = scope
        found: list[_PassUnit] = []
        rows = session.scalars(
            select(_DocumentLanguage)
            .where(_DocumentLanguage.status == _PassStatus.PENDING)
            .order_by(_DocumentLanguage.position, _DocumentLanguage.document_id)
        )
        waiting: set[int] = set()
        for row in rows:
            if (row.document_id, row.language_id) in skip or row.document_id in waiting:
                continue
            earlier = session.scalars(
                select(_DocumentLanguage).where(
                    _DocumentLanguage.document_id == row.document_id,
                    _DocumentLanguage.position < row.position,
                    _DocumentLanguage.status.in_((_PassStatus.PENDING, _PassStatus.PROCESSING)),
                )
            ).first()
            if earlier is not None:
                continue  # an earlier language of the file goes first
            origin = self.deepener._origin(session, row.document_id, source_id, only_file)
            if origin is None:
                continue
            code = session.scalar(select(_Language.language).where(_Language.id == row.language_id))
            spec = self.file_types.for_path(origin.file_path)
            found.append(
                _PassUnit(
                    row.document_id,
                    row.language_id,
                    code or "",
                    row.position,
                    origin.file_path,
                    origin.source_id,
                    spec.id if spec else "",
                )  # fmt: skip
            )
            waiting.add(row.document_id)
            if len(found) >= limit:
                break
        return found

    # ----- reading one file --------------------------------------------------------------------

    def read(
        self,
        unit: _PassUnit,
        run_id: int | None,
        tier: _TierView | None,
        remote_tier: _TierView | None,
        router: _Router | None,
        outbox,
        stop: Callable[[], bool],
    ) -> str:
        """Read the file's pages that need OCR in the pass's language. Returns "done", "away"
        (images sent to a remote tier), "skipped" or "stopped"."""
        reader = self.file_types.reader_for(unit.path)
        language = next((s for s in self.languages() if s.id == unit.language_code), None)
        if reader is None or language is None or tier is None:
            return "skipped"
        with self.database.session() as session:
            row = session.get(_DocumentLanguage, unit.key)
            if row is None:
                return "skipped"
            row.status, row.started_at, row.error_message = _PassStatus.PROCESSING, _now(), None
            pages = {
                p.page_number: (p.id, p.source)
                for p in session.scalars(
                    select(_PdfPage).where(
                        _PdfPage.document_id == unit.document_id,
                        _PdfPage.status == _PageState.DONE,
                    )
                )
            }
            done = set(
                session.scalars(
                    select(_PdfPage.page_number)
                    .join(_PdfPageQuick, _PdfPageQuick.page_id == _PdfPage.id)
                    .where(
                        _PdfPage.document_id == unit.document_id,
                        _PdfPageQuick.language_id == unit.language_id,
                    )
                )
            )
            away = self.deepener.remote.staged(
                session, unit.document_id, unit.language_id, self.PHASE
            )
        outcome = "done"
        try:
            for number, page in _PageOcr.pages(
                reader, Path(unit.path), self.file_types.reader_for, True, "quick"
            ):
                entry = pages.get(number)
                if entry is None or entry[1] is _PageSource.NATIVE:
                    continue
                if number in done or number in away:
                    continue
                if stop():
                    outcome = "stopped"
                    break
                result = self._page(
                    unit, language, number, entry, page, run_id, tier, remote_tier, router, outbox
                )
                if result == "away":
                    outcome = "away"
        except BaseException:
            self._back_to_pending(unit)
            raise
        if outcome == "stopped":
            self._back_to_pending(unit)
            return outcome
        with self.database.session() as session:
            self.try_finish(session, unit.document_id, unit.language_id)
        return outcome

    def _back_to_pending(self, unit: _PassUnit) -> None:
        with self.database.session() as session:
            row = session.get(_DocumentLanguage, unit.key)
            if row is not None and row.status is _PassStatus.PROCESSING:
                row.status = _PassStatus.PENDING

    def _page(
        self,
        unit: _PassUnit,
        language: LanguageSpec,
        number: int,
        entry: tuple[int, _PageSource],
        page,
        run_id: int | None,
        tier: _TierView,
        remote_tier: _TierView | None,
        router: _Router | None,
        outbox,
    ) -> str:
        page_id, source = entry
        regions: list = [None] if source is _PageSource.OCR else list(page.image_regions)
        if not regions:
            return "skipped"
        covered = 1.0 if regions == [None] else _PageOcr.covered(page)
        hybrid = tier.id == HYBRID
        local = self.tiers.hybrid_parts()[0] if hybrid else tier

        def meter_for(view: _TierView) -> _PageMeter:
            return _PageMeter(
                self.credits,
                source_id=unit.source_id,
                run_id=run_id,
                label=unit.path,
                language=unit.language_code,
                additional_language=True,
                wallet=view.wallet,
            )

        meter = meter_for(local)
        factor, cost = meter.quote(page.width_pt, page.height_pt, covered)
        away = bool(remote_tier) and (
            (not hybrid and tier.asynchronous)
            or (hybrid and router is not None and router.remote(factor, "quick"))
        )
        if away:
            meter = meter_for(remote_tier)
            factor, cost = meter.quote(page.width_pt, page.height_pt, covered)
        executor = (remote_tier if away else local).executor
        if executor is None:
            raise _OcrModelMissingError("OCR isn't available: no processing tier can read it.")
        held = meter.reserve(cost)
        try:
            images = [(index, page.render(region)) for index, region in enumerate(regions)]
            if away:
                return self._stage(
                    unit, language, number, images, factor, cost, held, meter, run_id,
                    remote_tier, outbox,
                )  # fmt: skip
            started = time.perf_counter()
            results = [
                executor.recognize(
                    OcrRequest(
                        key=self._key(unit, number, index),
                        image=image,
                        language=language,
                        phase="quick",
                        size_factor=factor,
                    )
                )
                for index, image in images
            ]
            duration = int((time.perf_counter() - started) * 1000)
        except BaseException:
            meter.release(held)
            raise
        charged = meter.commit(held, cost, number, factor, "quick", count_page=False)
        with self.database.session() as session:
            row = session.get(_PdfPage, page_id)
            if row is not None:
                self.merge(session, row, unit.language_id, language, results, duration)
                self.deepener._record(
                    session, unit.source_id, unit.file_type, unit.language_code, row, "quick",
                    [(0, r) for r in results], duration, charged, factor, len(results),
                )  # fmt: skip
        return "done"

    @staticmethod
    def _key(unit: _PassUnit, number: int, region: int) -> str:
        return f"d{unit.document_id}.l{unit.language_id}.language.{number}:{region}@0"

    # ----- merging what the language read ------------------------------------------------------

    @staticmethod
    def merge(
        session: Session,
        page: _PdfPage,
        language_id: int,
        language: LanguageSpec,
        results: list[OcrResult],
        duration_ms: int,
    ) -> int:
        """Add the lines `language` read believably to the page, and record that it was read in
        the language. Returns the number of lines added."""
        found: list[tuple[str, float]] = []
        boxes: list[tuple[float, float, float, float] | None] = []
        for result in results:
            lines = result.lines or tuple(
                (line, result.confidence) for line in result.text.splitlines()
            )
            placed = result.boxes if len(result.boxes) == len(result.lines) else ()
            for index, (line, score) in enumerate(lines):
                if _LanguageDetector.believable([(line, score)], language):
                    found.append((line, score))
                    boxes.append(placed[index] if placed else None)
        text, added = _Merge.lines(page.text, [line for line, _ in found])
        _PageStore.save_boxes(
            session,
            page.id,
            tuple((found[i][0].strip(), *boxes[i]) for i in added if boxes[i] is not None),
        )
        if added:
            before = len([line for line in page.text.split("\n") if line.strip()])
            gained = sum(found[i][1] for i in added)
            page.confidence = (page.confidence * before + gained) / max(before + len(added), 1)
            page.text, page.char_count = text, len(text)
        quick = session.scalars(
            select(_PdfPageQuick).where(
                _PdfPageQuick.page_id == page.id, _PdfPageQuick.language_id == language_id
            )
        ).first()
        if quick is None:
            quick = _PdfPageQuick(page_id=page.id, language_id=language_id, completed_at="")
            session.add(quick)
        quick.region_count = len(results) if page.source is _PageSource.MIXED else 0
        quick.engine = next((r.engine for r in reversed(results) if r.engine), "")
        quick.confidence = sum(score for _, score in found) / len(found) if found else 0.0
        quick.line_count = len(found)
        quick.char_count = sum(len(line) for line, _ in found)
        quick.duration_ms = duration_ms
        quick.completed_at = _now()
        session.flush()
        return len(added)

    def try_finish(self, session: Session, document_id: int, language_id: int) -> bool:
        """The pass is done once every page that needed OCR has been read in the language."""
        row = session.get(_DocumentLanguage, (document_id, language_id))
        if row is None or row.status is _PassStatus.DONE:
            return False
        needing = session.scalars(
            select(_PdfPage.id).where(
                _PdfPage.document_id == document_id,
                _PdfPage.source.in_((_PageSource.OCR, _PageSource.MIXED)),
            )
        ).all()
        read = set(
            session.scalars(
                select(_PdfPageQuick.page_id).where(
                    _PdfPageQuick.page_id.in_(needing), _PdfPageQuick.language_id == language_id
                )
            )
        )
        if any(page_id not in read for page_id in needing):
            return False
        _PageStore.finish_pass(session, document_id, language_id)
        return True

    # ----- on a remote tier --------------------------------------------------------------------

    def _stage(
        self,
        unit: _PassUnit,
        language: LanguageSpec,
        number: int,
        images: list[tuple[int, object]],
        factor: float,
        cost: int,
        held: int,
        meter: _PageMeter,
        run_id: int | None,
        remote_tier: _TierView,
        outbox,
    ) -> str:
        requests = [
            OcrRequest(
                key=self._key(unit, number, index),
                image=image,
                language=language,
                phase="quick",
                size_factor=factor,
            )
            for index, image in images
        ]
        before = len(meter.ledger_ids)
        charged = meter.commit(held, cost, number, factor, "quick", count_page=False)
        ledger = tuple(meter.ledger_ids[before:])
        each, extra = divmod(charged, max(len(requests), 1))
        ids: list[int] = []
        with self.database.session() as session:
            for position, (request, (index, _image)) in enumerate(
                zip(requests, images, strict=True)
            ):
                row = _RemoteJobPage(
                    document_id=unit.document_id,
                    page_number=number,
                    region=index,
                    language_id=unit.language_id,
                    phase=self.PHASE,
                    angle=0,
                    request_key=request.key,
                    state=_JobPageState.STAGED,
                    size_factor_milli=round(factor * 1000),
                    credits_milli=each + (extra if position == 0 else 0),
                    ledger_ids=",".join(str(i) for i in ledger) if position == 0 else "",
                    run_id=run_id,
                    wallet=remote_tier.wallet,
                )
                session.add(row)
                session.flush()
                ids.append(row.id)
        if outbox is not None:
            outbox.add(requests, ids)
        return "away"

    def complete(
        self,
        session: Session,
        document_id: int,
        number: int,
        language_id: int,
        images: list[_RemoteJobPage],
        answers: list[OcrResult],
    ) -> None:
        """A pass's images came back from a remote tier: merge them into the page."""
        page = session.scalars(
            select(_PdfPage).where(
                _PdfPage.document_id == document_id, _PdfPage.page_number == number
            )
        ).first()
        language_row = session.get(_Language, language_id)
        language = next(
            (s for s in self.languages() if language_row and s.id == language_row.language), None
        )
        if page is None or language is None:
            return
        self.merge(session, page, language_id, language, answers, 0)
        first = self.deepener._origin(session, document_id, None, None)
        self.deepener._record(
            session, first.source_id if first else None,
            (self.file_types.for_path(first.file_path).id if first else ""),
            language.id, page, "quick", [(0, r) for r in answers],
            0, sum(i.credits_milli for i in images),
            sum(i.size_factor_milli for i in images[:1]) / 1000, len(answers),
        )  # fmt: skip
        self.try_finish(session, document_id, language_id)


def _now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["_PassUnit", "_Passes"]
