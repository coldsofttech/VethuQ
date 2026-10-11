"""Reading statistics from the daily totals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from vethuq._db import (
    _DocumentIndex,
    _PdfPage,
    _Source,
    _UsageDaily,
    _UsageFailure,
)
from vethuq._db.values import _PageSource
from vethuq._settings import _ConfidenceSettings
from vethuq._sources import _Sources
from vethuq._stats.usage import _Bands
from vethuq.enums import (
    ConfidenceBand,
    FileStatus,
    SortOrder,
    StatsGroupBy,
    StatsSortBy,
)

PURGED = "(purged source)"


@dataclass
class _Row:
    key: str
    files: int | None = None
    pages: int = 0
    native_pages: int = 0
    ocr_pages: int = 0
    passes: int = 0
    confidence_sum: float = 0.0
    bands: dict[str, int] = field(default_factory=lambda: {b.value: 0 for b in ConfidenceBand})
    duration_ms: int = 0
    credits_milli: int = 0
    failures: int | None = None

    @property
    def confidence(self) -> float | None:
        return self.confidence_sum / self.pages if self.pages else None


class _Stats:
    COLUMNS = {
        StatsGroupBy.LANGUAGE: _UsageDaily.language,
        StatsGroupBy.FILE_TYPE: _UsageDaily.file_type,
        StatsGroupBy.ENGINE: _UsageDaily.engine,
        StatsGroupBy.PAGE_SOURCE: _UsageDaily.page_source,
        StatsGroupBy.BAND: _UsageDaily.band,
        StatsGroupBy.DAY: _UsageDaily.day,
    }

    @staticmethod
    def day(value: date | datetime | str | None, name: str) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10]).isoformat()
            except ValueError:
                raise ValueError(f"{name} must be a date or a YYYY-MM-DD string.") from None
        raise TypeError(f"{name} must be a date or a YYYY-MM-DD string.")

    @staticmethod
    def _source_id(session: Session, source: int | str | Path) -> int:
        return _Sources.get(session, source, include_removed=True).id

    @staticmethod
    def _filters(
        statement: Select,
        session: Session,
        *,
        source: int | str | Path | None,
        language: str | None,
        file_type: str | None,
        engine: str | None,
        page_source: str | None,
        band: ConfidenceBand | str | None,
        since: str | None,
        until: str | None,
    ) -> Select:
        if source is not None:
            statement = statement.where(_UsageDaily.source_id == _Stats._source_id(session, source))
        if language is not None:
            statement = statement.where(_UsageDaily.language == str(language).strip().lower())
        if file_type is not None:
            statement = statement.where(_UsageDaily.file_type == str(file_type).strip().lower())
        if engine is not None:
            statement = statement.where(_UsageDaily.engine == engine)
        if page_source is not None:
            statement = statement.where(
                _UsageDaily.page_source
                == _Sources._coerce(_PageSourceEnum, page_source, "page_source").value
            )
        if band is not None:
            statement = statement.where(
                _UsageDaily.band == _Sources._coerce(ConfidenceBand, band, "band").value
            )
        if since is not None:
            statement = statement.where(_UsageDaily.day >= since)
        if until is not None:
            statement = statement.where(_UsageDaily.day <= until)
        return statement

    @staticmethod
    def _measures():
        return (
            func.sum(_UsageDaily.pages),
            func.sum(
                case(
                    (_UsageDaily.page_source == _PageSource.NATIVE.value, _UsageDaily.pages),
                    else_=0,
                )
            ),
            func.sum(_UsageDaily.passes),
            func.sum(_UsageDaily.confidence_sum),
            func.sum(_UsageDaily.duration_ms),
            func.sum(_UsageDaily.credits_milli),
            *(
                func.sum(case((_UsageDaily.band == b.value, _UsageDaily.pages), else_=0))
                for b in ConfidenceBand
            ),
        )

    @staticmethod
    def _fill(row: _Row, values) -> _Row:
        pages, native, passes, conf, ms, credits, *bands = (v or 0 for v in values)
        row.pages, row.native_pages, row.ocr_pages = int(pages), int(native), int(pages - native)
        row.passes, row.confidence_sum = int(passes), float(conf)
        row.duration_ms, row.credits_milli = int(ms), int(credits)
        row.bands = {b.value: int(n) for b, n in zip(ConfidenceBand, bands, strict=True)}
        return row

    @staticmethod
    def overview(
        session: Session,
        *,
        group_by: StatsGroupBy | str = StatsGroupBy.SOURCE,
        source: int | str | Path | None = None,
        language: str | None = None,
        file_type: str | None = None,
        engine: str | None = None,
        page_source: str | None = None,
        band: ConfidenceBand | str | None = None,
        since: date | datetime | str | None = None,
        until: date | datetime | str | None = None,
        sort_by: StatsSortBy | str = StatsSortBy.KEY,
        order: SortOrder | str = SortOrder.ASC,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[_Row, list[_Row]]:
        group = _Sources._coerce(StatsGroupBy, group_by, "group_by")
        sort = _Sources._coerce(StatsSortBy, sort_by, "sort_by")
        direction = _Sources._coerce(SortOrder, order, "order")
        if offset < 0 or (limit is not None and limit < 0):
            raise ValueError("limit and offset can't be negative.")
        filters = {
            "source": source,
            "language": language,
            "file_type": file_type,
            "engine": engine,
            "page_source": page_source,
            "band": band,
            "since": _Stats.day(since, "since"),
            "until": _Stats.day(until, "until"),
        }
        measures = _Stats._measures()
        total = _Stats._fill(
            _Row("total"),
            session.execute(_Stats._filters(select(*measures), session, **filters)).one(),
        )
        if group is StatsGroupBy.SOURCE:
            statement = select(_UsageDaily.source_id, *measures).group_by(_UsageDaily.source_id)
        else:
            column = _Stats.COLUMNS[group]
            statement = select(column, *measures).group_by(column)
        rows: dict[object, _Row] = {}
        paths = dict(session.execute(select(_Source.id, _Source.path)).all())
        for key, *values in session.execute(_Stats._filters(statement, session, **filters)):
            label = (
                (paths.get(key, PURGED) if key else PURGED)
                if group is StatsGroupBy.SOURCE
                else (key or "(none)")
            )
            rows[key] = _Stats._fill(_Row(str(label)), values)
        _Stats._failures(session, group, rows, total, filters)
        if group is StatsGroupBy.SOURCE:
            counts = dict(
                session.execute(
                    select(_DocumentIndex.source_id, func.count())
                    .where(_DocumentIndex.status == FileStatus.INDEXED)
                    .group_by(_DocumentIndex.source_id)
                ).all()
            )
            for key, row in rows.items():
                row.files = counts.get(key, 0) if key else None
            total.files = sum(counts.get(k, 0) for k in rows if k) or None
        result = list(rows.values())
        attribute = {
            StatsSortBy.KEY: lambda r: r.key.casefold(),
            StatsSortBy.FILES: lambda r: r.files or 0,
            StatsSortBy.PAGES: lambda r: r.pages,
            StatsSortBy.OCR_PAGES: lambda r: r.ocr_pages,
            StatsSortBy.CONFIDENCE: lambda r: -1 if r.confidence is None else r.confidence,
            StatsSortBy.DURATION: lambda r: r.duration_ms,
            StatsSortBy.CREDITS: lambda r: r.credits_milli,
            StatsSortBy.FAILURES: lambda r: r.failures or 0,
        }[sort]
        result.sort(
            key=lambda r: (attribute(r), r.key.casefold()), reverse=direction is SortOrder.DESC
        )
        end = None if limit is None else offset + limit
        return total, result[offset:end]

    @staticmethod
    def _failures(session, group, rows, total, filters) -> None:
        """Failures by group, where the failure totals have that dimension."""
        if group not in (StatsGroupBy.SOURCE, StatsGroupBy.FILE_TYPE, StatsGroupBy.DAY):
            return
        if any(filters[k] for k in ("language", "engine", "page_source", "band")):
            return  # failures have no such dimensions
        statement = select(func.sum(_UsageFailure.count))
        if filters["source"] is not None:
            statement = statement.where(
                _UsageFailure.source_id == _Stats._source_id(session, filters["source"])
            )
        if filters["file_type"]:
            statement = statement.where(
                _UsageFailure.file_type == str(filters["file_type"]).lower()
            )
        if filters["since"]:
            statement = statement.where(_UsageFailure.day >= filters["since"])
        if filters["until"]:
            statement = statement.where(_UsageFailure.day <= filters["until"])
        column = {
            StatsGroupBy.SOURCE: _UsageFailure.source_id,
            StatsGroupBy.FILE_TYPE: _UsageFailure.file_type,
            StatsGroupBy.DAY: _UsageFailure.day,
        }[group]
        found: dict = {}
        for count, key in session.execute(statement.add_columns(column).group_by(column)):
            found[key] = int(count or 0)
        for key, row in rows.items():
            row.failures = found.get(key, 0)
        for key, count in found.items():
            if key not in rows:
                rows[key] = _Row(
                    str(
                        key
                        if group is not StatsGroupBy.SOURCE
                        else (
                            session.get(_Source, key).path
                            if key and session.get(_Source, key)
                            else PURGED
                        )
                    ),
                    failures=count,
                )
        total.failures = sum(found.values())

    @staticmethod
    def failure_codes(
        session: Session,
        *,
        source: int | str | Path | None = None,
        file_type: str | None = None,
        since: date | datetime | str | None = None,
        until: date | datetime | str | None = None,
    ) -> dict[str, int]:
        statement = select(_UsageFailure.code, func.sum(_UsageFailure.count)).group_by(
            _UsageFailure.code
        )
        if source is not None:
            statement = statement.where(
                _UsageFailure.source_id == _Stats._source_id(session, source)
            )
        if file_type is not None:
            statement = statement.where(_UsageFailure.file_type == str(file_type).lower())
        if (day := _Stats.day(since, "since")) is not None:
            statement = statement.where(_UsageFailure.day >= day)
        if (day := _Stats.day(until, "until")) is not None:
            statement = statement.where(_UsageFailure.day <= day)
        return {
            code: int(n or 0) for code, n in session.execute(statement.order_by(_UsageFailure.code))
        }

    @staticmethod
    def low_confidence_pages(
        session: Session,
        *,
        source: int | str | Path | None = None,
        band: ConfidenceBand | str | None = None,
        limit: int | None = 100,
    ) -> list[tuple[str, int, float, ConfidenceBand, str]]:
        """Pages whose confidence is below the `medium` cut-off, worst first: (file path, page
        number, confidence, band, how it was read)."""
        bands = _ConfidenceSettings.get_bands(session)
        wanted = None if band is None else _Sources._coerce(ConfidenceBand, band, "band")
        statement = (
            select(
                _DocumentIndex.file_path, _PdfPage.page_number, _PdfPage.confidence, _PdfPage.source
            )
            .join(_DocumentIndex, _DocumentIndex.document_id == _PdfPage.document_id)
            .where(
                _PdfPage.confidence < bands[1] / 100,
                _DocumentIndex.status == FileStatus.INDEXED,
            )
            .order_by(_PdfPage.confidence, _DocumentIndex.file_path, _PdfPage.page_number)
        )
        if source is not None:
            statement = statement.where(
                _DocumentIndex.source_id == _Stats._source_id(session, source)
            )
        found = []
        for path, number, confidence, how in session.execute(statement):
            this = _Bands.of(confidence, bands)
            if wanted is None or this is wanted:
                found.append((path, number, confidence, this, how.value))
        return found if limit is None else found[:limit]


_PageSourceEnum = _PageSource
