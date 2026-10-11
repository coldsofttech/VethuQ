"""The deeper OCR phases (`moderate`, `deep`): reading pages again at other angles.

The quick phase reads each page once, upright. A deeper phase reads the pages that needed OCR again
at the angles its add-on names, with the phase's own models, and adds what it finds to the page's
text. Phases are cumulative and go in order, so every page has had `moderate` before any gets
`deep`. A page's progress is a row in `pdf_pages_phases` per language and phase, saved as soon as
the page is read, so a run that stops loses nothing.

A page is read again, from its file, only when it has something to find: a scanned page (the whole
page), a page with images on a text layer (the images) or a page with pictures the quick phase left
alone (a Markdown file's, read from `moderate`: upright too, since quick skipped them). Text, CSV
and Markdown text have no OCR in them and are never turned.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from vethuq._credits import _Clock, _PageMeter, _Pricing
from vethuq._db import (
    _Database,
    _DocumentIndex,
    _Language,
    _PdfPage,
    _PdfPagePhase,
    _PdfPageQuick,
    _RemoteJobPage,
    _Source,
)
from vethuq._db.values import _JobPageState, _PageSource, _PageState
from vethuq._errors import _OcrModelMissingError
from vethuq._filetypes import _FileTypeCatalog
from vethuq._ocr import _PageOcr
from vethuq._settings import _ConfidenceSettings
from vethuq._stats import _PageFact, _Usage
from vethuq._tiers import HYBRID, _Router, _Tiers, _TierView
from vethuq.enums import FileStatus
from vethuq_addon_api import LanguageSpec, OcrPhaseSpec, OcrRequest, OcrResult

if TYPE_CHECKING:
    from vethuq._credits import _Credits
    from vethuq._indexing.remote import _Outbox, _Remote

_logger = logging.getLogger("vethuq.indexing")


@dataclass(frozen=True)
class _Unit:
    """One page, in one language, that still needs a phase's angles read."""

    page_id: int
    document_id: int
    page_number: int
    language_id: int
    language_code: str
    path: str
    source_id: int
    file_type: str
    page_source: _PageSource
    deferred: bool  # pictures the quick phase left alone: read upright too, the first time

    @property
    def key(self) -> tuple[int, int]:
        return self.page_id, self.language_id


class _Merge:
    """Adding what a rotated read found to what a page already says."""

    # A line found at a rotated angle must be at least this confident to be kept: odd angles read
    # drawing strokes and noise as text far more often than upright text does.
    MIN_ROTATED_SCORE = 0.5

    @staticmethod
    def normalize(line: str) -> str:
        return " ".join(line.casefold().split())

    @staticmethod
    def lines(existing_text: str, new_lines: list[str]) -> tuple[str, list[int]]:
        """`new_lines` added to `existing_text`, leaving out what it already says. A new line
        already inside an existing one is dropped; an existing line inside a new, longer one is
        replaced by it (a word read partly at one angle and whole at another ends up once).
        Returns the text and the indexes into `new_lines` of the lines that were added."""
        lines = existing_text.split("\n") if existing_text else []
        normalized = [_Merge.normalize(line) for line in lines]
        added: list[int] = []
        for index, line in enumerate(new_lines):
            new = _Merge.normalize(line)
            if not new or any(new in existing for existing in normalized):
                continue
            keep = [i for i, existing in enumerate(normalized) if existing and existing not in new]
            lines = [lines[i] for i in keep]
            normalized = [normalized[i] for i in keep]
            lines.append(line.strip())
            normalized.append(new)
            added.append(index)
        return "\n".join(lines), added

    @staticmethod
    def reads(
        session: Session,
        page: _PdfPage,
        language_id: int,
        phase: str,
        reads: list[tuple[int, OcrResult]],
        regions: int,
        duration_ms: int,
    ) -> int:
        """Merge the answers (one per angle and image) into `page` and record the phase as done
        for the language. Returns the number of lines added."""
        found: list[tuple[str, float]] = []
        for angle, result in reads:
            lines = result.lines or tuple(
                (line, result.confidence) for line in result.text.splitlines()
            )
            for line, score in lines:
                if angle % 360 and score < _Merge.MIN_ROTATED_SCORE:
                    continue
                found.append((line, float(score)))
        text, added = _Merge.lines(page.text, [line for line, _ in found])
        if added:
            before = len([line for line in page.text.split("\n") if line.strip()])
            gained = sum(found[i][1] for i in added)
            # The page's confidence is the average over its lines: new lines pull it toward theirs.
            page.confidence = (page.confidence * before + gained) / max(before + len(added), 1)
            page.text, page.char_count = text, len(text)
            if page.source is _PageSource.NATIVE:
                page.source = _PageSource.MIXED  # the text now comes partly from OCR
        angles = sorted({angle for angle, _ in reads})
        engine = next((r.engine for _, r in reversed(reads) if r.engine), "")
        row = session.scalars(
            select(_PdfPagePhase).where(
                _PdfPagePhase.page_id == page.id,
                _PdfPagePhase.language_id == language_id,
                _PdfPagePhase.phase == phase,
            )
        ).first()
        if row is None:
            row = _PdfPagePhase(
                page_id=page.id, language_id=language_id, phase=phase, completed_at=""
            )
            session.add(row)
        row.angles = ",".join(str(a) for a in angles)
        row.region_count = regions
        row.lines_added = len(added)
        row.char_count = sum(len(found[i][0]) for i in added)
        row.engine, row.duration_ms = engine, duration_ms
        row.completed_at = datetime.now(UTC).isoformat()
        session.flush()
        return len(added)


class _Deepener:
    """Finds the pages a phase still has to read and reads them, here or on a remote tier."""

    def __init__(
        self,
        database: _Database,
        file_types: _FileTypeCatalog,
        tiers: _Tiers,
        credits: _Credits,
        remote: _Remote,
        phases: Callable[[], list[OcrPhaseSpec]],
        languages: Callable[[], list[LanguageSpec]],
    ) -> None:
        self.database = database
        self.file_types = file_types
        self.tiers = tiers
        self.credits = credits
        self.remote = remote
        self.phases = phases
        self.languages = languages

    # ----- which phases ------------------------------------------------------------------------

    def deeper(self, engine: str) -> list[OcrPhaseSpec]:
        """The installed phases after quick, in order, up to the one the engine setting names."""
        limit = _PageOcr.order(engine)
        found = [
            spec
            for spec in self.phases()
            if spec.available
            and _PageOcr.order(spec.id) > _PageOcr.order("quick")
            and _PageOcr.order(spec.id) <= limit
        ]
        return sorted(found, key=lambda spec: (spec.order, spec.id))

    def missing(self, engine: str) -> list[str]:
        """The phases the engine setting reaches whose add-on isn't installed."""
        have = {spec.id for spec in self.phases() if spec.available}
        return [
            phase
            for phase in _PageOcr.ORDER
            if 1 < _PageOcr.order(phase) <= _PageOcr.order(engine) and phase not in have
        ]

    # ----- which pages -------------------------------------------------------------------------

    def units(
        self,
        session: Session,
        phase: str,
        scope: tuple[int | None, str | None],
        skip: set[tuple[int, int, str]],
        limit: int,
    ) -> list[_Unit]:
        """Up to `limit` pages (each in a language) that still need `phase`. `scope` is the run's
        source and file; `skip` is what this run already tried."""
        source_id, only_file = scope
        wanted = _PageOcr.order(phase)
        statement = (
            select(_PdfPage)
            .where(
                _PdfPage.status == _PageState.DONE,
                or_(
                    _PdfPage.source.in_((_PageSource.OCR, _PageSource.MIXED)),
                    _PdfPage.deepen_from.is_not(None),
                ),
            )
            .order_by(_PdfPage.id)
        )
        found: list[_Unit] = []
        after = 0
        while len(found) < limit:
            batch = list(session.scalars(statement.where(_PdfPage.id > after).limit(200)))
            if not batch:
                break
            after = batch[-1].id
            ids = [p.id for p in batch]
            done = {
                (row.page_id, row.language_id)
                for row in session.scalars(
                    select(_PdfPagePhase).where(
                        _PdfPagePhase.page_id.in_(ids), _PdfPagePhase.phase == phase
                    )
                )
            }
            read_in: dict[int, list[int]] = {}
            for page_id, language_id in session.execute(
                select(_PdfPageQuick.page_id, _PdfPageQuick.language_id).where(
                    _PdfPageQuick.page_id.in_(ids)
                )
            ):
                read_in.setdefault(page_id, []).append(language_id)
            for page in batch:
                if page.deepen_from and wanted < _PageOcr.order(page.deepen_from):
                    continue
                origin = self._origin(session, page.document_id, source_id, only_file)
                if origin is None:
                    continue
                languages = read_in.get(page.id) or [self._language_of(session, origin)]
                for language_id in languages:
                    if language_id is None or (page.id, language_id) in done:
                        continue
                    if (page.id, language_id, phase) in skip:
                        continue
                    code = session.scalar(
                        select(_Language.language).where(_Language.id == language_id)
                    )
                    spec = self.file_types.for_path(origin.file_path)
                    found.append(
                        _Unit(
                            page.id,
                            page.document_id,
                            page.page_number,
                            language_id,
                            code or "",
                            origin.file_path,
                            origin.source_id,
                            spec.id if spec else "",
                            page.source,
                            bool(page.deepen_from),
                        )  # fmt: skip
                    )
                    if len(found) >= limit:
                        return found
        return found

    @staticmethod
    def _origin(
        session: Session, document_id: int, source_id: int | None, only_file: str | None
    ) -> _DocumentIndex | None:
        """A file of the document that is indexed, still there and inside the run's scope."""
        statement = select(_DocumentIndex).where(
            _DocumentIndex.document_id == document_id,
            _DocumentIndex.status == FileStatus.INDEXED,
            _DocumentIndex.removed_at.is_(None),
        )
        if only_file is not None:
            statement = statement.where(_DocumentIndex.file_path == only_file)
        elif source_id is not None:
            statement = statement.where(_DocumentIndex.source_id == source_id)
        for row in session.scalars(statement.order_by(_DocumentIndex.id)):
            if Path(row.file_path).is_file():
                return row
        return None

    def _language_of(self, session: Session, row: _DocumentIndex) -> int | None:
        """The language a file is read in: its source's first, else the default."""
        from vethuq._languages import _Languages  # noqa: PLC0415 - avoids an import cycle

        source = session.get(_Source, row.source_id)
        if source is None:
            return None
        codes = source.language_codes or _Languages.default_ids(session, self.languages())
        return session.scalar(select(_Language.id).where(_Language.language == codes[0]))

    def pending(self, session: Session, engine: str) -> int:
        """How many (page, language) pairs the phases up to `engine` still have to read."""
        total = 0
        for spec in self.deeper(engine):
            total += len(self.units(session, spec.id, (None, None), set(), 10**9))
        return total

    # ----- reading one page --------------------------------------------------------------------

    def read(
        self,
        unit: _Unit,
        spec: OcrPhaseSpec,
        run_id: int | None,
        tier: _TierView | None,
        remote_tier: _TierView | None,
        router: _Router | None,
        outbox: _Outbox | None,
        stop: Callable[[], bool],
    ) -> str:
        """Read `unit` at the phase's angles. Returns "done", "away" (images sent to a remote
        tier), "skipped" (nothing there to read, or no add-on reads a picture's format) or
        "stopped". Raises `CreditsExhaustedError` when the credits run out."""
        reader = self.file_types.reader_for(unit.path)
        if reader is None:
            return "skipped"
        language = next((s for s in self.languages() if s.id == unit.language_code), None)
        if language is None:
            return "skipped"
        outcome = "skipped"
        for _number, page in _PageOcr.pages(
            reader, Path(unit.path), self.file_types.reader_for, True, spec.id, unit.page_number
        ):
            outcome = self._page(
                unit, spec, language, page, run_id, tier, remote_tier, router, outbox, stop
            )
        return outcome

    def _page(
        self,
        unit: _Unit,
        spec: OcrPhaseSpec,
        language: LanguageSpec,
        page,
        run_id: int | None,
        tier: _TierView | None,
        remote_tier: _TierView | None,
        router: _Router | None,
        outbox: _Outbox | None,
        stop: Callable[[], bool],
    ) -> str:
        if unit.page_source is _PageSource.OCR and not unit.deferred:
            regions: list = [None]  # a scanned page: all of it
        else:
            regions = list(page.image_regions)  # the images on it, or the pictures it links to
        if not regions or tier is None:
            return "skipped"
        angles = list(spec.angles)
        with self.database.session() as session:
            earlier = session.scalars(
                select(_PdfPagePhase.id).where(_PdfPagePhase.page_id == unit.page_id)
            ).first()
        if unit.deferred and earlier is None and 0 not in angles:
            angles = [0, *angles]  # the quick phase never read these pictures upright
        covered = 1.0 if regions == [None] else _PageOcr.covered(page)

        hybrid = tier.id == HYBRID
        local = self.tiers.hybrid_parts()[0] if hybrid else tier
        meter = _PageMeter(
            self.credits,
            source_id=unit.source_id,
            run_id=run_id,
            label=unit.path,
            language=unit.language_code,
            additional_language=False,
            wallet=local.wallet,
        )
        factor, cost = meter.quote_rotated(
            page.width_pt, page.height_pt, covered, len(regions) * len(angles)
        )
        away = bool(remote_tier) and (
            (not hybrid and tier.asynchronous)
            or (hybrid and router is not None and router.remote(factor, spec.id))
        )
        if away:
            meter = _PageMeter(
                self.credits,
                source_id=unit.source_id,
                run_id=run_id,
                label=unit.path,
                language=unit.language_code,
                additional_language=False,
                wallet=remote_tier.wallet,
            )
            factor, cost = meter.quote_rotated(
                page.width_pt, page.height_pt, covered, len(regions) * len(angles)
            )
            executor = remote_tier.executor
        else:
            executor = local.executor
        if executor is None:
            raise _OcrModelMissingError("OCR isn't available: no processing tier can read it.")

        held = meter.reserve(cost)
        try:
            images = [(index, page.render(region)) for index, region in enumerate(regions)]
            if away:
                return self._stage(
                    unit, spec, language, images, angles, factor, cost, held, meter, run_id,
                    remote_tier, outbox,
                )  # fmt: skip
            started = time.perf_counter()
            reads: list[tuple[int, OcrResult]] = []
            for index, image in images:
                for angle in angles:
                    if stop():
                        meter.release(held)
                        return "stopped"
                    reads.append(
                        (
                            angle,
                            executor.recognize(
                                OcrRequest(
                                    key=self._key(unit, spec.id, index, angle),
                                    image=image,
                                    language=language,
                                    phase=spec.id,
                                    size_factor=factor,
                                    angle=angle,
                                )
                            ),
                        )
                    )
            duration = int((time.perf_counter() - started) * 1000)
        except BaseException:
            meter.release(held)
            raise
        charged = meter.commit(held, cost, unit.page_number, factor, spec.id, count_page=False)
        self._save(unit, spec, reads, len(regions), duration, charged, factor, len(angles))
        return "done"

    @staticmethod
    def _key(unit: _Unit, phase: str, region: int, angle: int) -> str:
        return (
            f"d{unit.document_id}.l{unit.language_id}.{phase}.{unit.page_number}:{region}@{angle}"
        )

    def _save(
        self,
        unit: _Unit,
        spec: OcrPhaseSpec,
        reads: list[tuple[int, OcrResult]],
        regions: int,
        duration_ms: int,
        credits_milli: int,
        factor: float,
        passes: int,
    ) -> None:
        with self.database.session() as session:
            page = session.get(_PdfPage, unit.page_id)
            if page is None:
                return
            _Merge.reads(session, page, unit.language_id, spec.id, reads, regions, duration_ms)
            self._record(
                session, unit.source_id, unit.file_type, unit.language_code, page, spec.id,
                reads, duration_ms, credits_milli, factor, passes,
            )  # fmt: skip

    @staticmethod
    def _record(
        session: Session,
        source_id: int | None,
        file_type: str,
        language_code: str,
        page: _PdfPage,
        phase: str,
        reads: list[tuple[int, OcrResult]],
        duration_ms: int,
        credits_milli: int,
        factor: float,
        passes: int,
    ) -> None:
        bands = _ConfidenceSettings.get_bands(session)
        _Usage.record_pages(
            session,
            _Clock.today(session).isoformat(),
            source_id,
            file_type,
            language_code,
            [
                _PageFact(
                    page_source=page.source.value,
                    phase=phase,
                    engine=next((r.engine for _, r in reversed(reads) if r.engine), ""),
                    size_bucket=_Pricing.bucket(factor),
                    confidence=page.confidence,
                    duration_ms=duration_ms,
                    credits_milli=credits_milli,
                    passes=passes,
                )
            ],
            bands,
        )

    # ----- on a remote tier --------------------------------------------------------------------

    def _stage(
        self,
        unit: _Unit,
        spec: OcrPhaseSpec,
        language: LanguageSpec,
        images: list[tuple[int, object]],
        angles: list[int],
        factor: float,
        cost: int,
        held: int,
        meter: _PageMeter,
        run_id: int | None,
        remote_tier: _TierView,
        outbox: _Outbox | None,
    ) -> str:
        """Pay for the page and stage its images, once per angle, to be sent in a job. The image
        is the same object for every angle, so a job holds it once."""
        requests: list[OcrRequest] = []
        order: list[tuple[int, int]] = []
        for index, image in images:
            for angle in angles:
                requests.append(
                    OcrRequest(
                        key=self._key(unit, spec.id, index, angle),
                        image=image,
                        language=language,
                        phase=spec.id,
                        size_factor=factor,
                        angle=angle,
                    )
                )
                order.append((index, angle))
        before = len(meter.ledger_ids)
        charged = meter.commit(held, cost, unit.page_number, factor, spec.id, count_page=False)
        ledger = tuple(meter.ledger_ids[before:])
        each, extra = divmod(charged, max(len(requests), 1))
        ids: list[int] = []
        with self.database.session() as session:
            for position, (request, (index, angle)) in enumerate(zip(requests, order, strict=True)):
                row = _RemoteJobPage(
                    document_id=unit.document_id,
                    page_number=unit.page_number,
                    region=index,
                    language_id=unit.language_id,
                    phase=spec.id,
                    angle=angle,
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
        phase: str,
        images: list[_RemoteJobPage],
        answers: list[OcrResult],
    ) -> None:
        """A deeper page's images came back from a remote tier: merge them into the page."""
        page = session.scalars(
            select(_PdfPage).where(
                _PdfPage.document_id == document_id, _PdfPage.page_number == number
            )
        ).first()
        if page is None:
            return
        reads = [(row.angle, answer) for row, answer in zip(images, answers, strict=True)]
        regions = len({row.region for row in images})
        _Merge.reads(session, page, language_id, phase, reads, regions, 0)
        first = session.scalars(
            select(_DocumentIndex).where(_DocumentIndex.document_id == document_id)
        ).first()
        code = session.scalar(select(_Language.language).where(_Language.id == language_id)) or ""
        file_type = self.file_types.for_path(first.file_path) if first else None
        self._record(
            session, first.source_id if first else None, file_type.id if file_type else "",
            code, page, phase, reads, 0, sum(i.credits_milli for i in images),
            sum(i.size_factor_milli for i in images[:1]) / 1000, len(images),
        )  # fmt: skip


__all__ = ["_Deepener", "_Merge", "_Unit"]
