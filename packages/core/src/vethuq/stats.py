"""Statistics about the work VethuQ has done: `VethuQ().stats`.

They come from daily totals kept as pages are read (never names, paths or text), so they stay
after files change or a source is purged. Native pages need no OCR and cost nothing; `ocr_pages`
are the pages that were read by OCR (scanned and mixed).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from vethuq._db import _Database
from vethuq._stats import _Row, _Stats
from vethuq.enums import ConfidenceBand, SortOrder, StatsGroupBy, StatsSortBy

__all__ = [
    "ConfidenceBand",
    "LowConfidencePage",
    "SortOrder",
    "Stats",
    "StatsGroupBy",
    "StatsOverview",
    "StatsRow",
    "StatsSortBy",
]


@dataclass(frozen=True)
class StatsRow:
    """The totals for one group (or for everything)."""

    key: str  # what the row is for: a source's path, a language id, a day, ...
    files: int | None  # files currently indexed (only when grouped by source)
    pages: int
    native_pages: int  # read from the file's own text
    ocr_pages: int  # read by OCR
    passes: int  # OCR passes
    confidence: float | None  # average over the pages, 0 to 1
    bands: dict[str, int]  # pages by confidence band
    duration_ms: int  # time spent in OCR
    ms_per_ocr_page: float | None
    pages_per_minute: float | None  # OCR pages per minute of OCR time
    credits: float
    failures: int | None  # files that failed (by source, file type or day)

    @classmethod
    def _from_row(cls, row: _Row) -> StatsRow:
        minutes = row.duration_ms / 60000
        return cls(
            key=row.key,
            files=row.files,
            pages=row.pages,
            native_pages=row.native_pages,
            ocr_pages=row.ocr_pages,
            passes=row.passes,
            confidence=row.confidence,
            bands=dict(row.bands),
            duration_ms=row.duration_ms,
            ms_per_ocr_page=row.duration_ms / row.ocr_pages if row.ocr_pages else None,
            pages_per_minute=row.ocr_pages / minutes if minutes > 0 else None,
            credits=row.credits_milli / 1000,
            failures=row.failures,
        )

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class StatsOverview:
    """The totals, and the rows they are made of."""

    total: StatsRow
    rows: list[StatsRow]
    group_by: StatsGroupBy

    def to_dict(self) -> dict[str, object]:
        return {
            "group_by": self.group_by.value,
            "total": self.total.to_dict(),
            "rows": [row.to_dict() for row in self.rows],
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class LowConfidencePage:
    """A page OCR wasn't sure of."""

    path: str
    page_number: int
    confidence: float
    band: ConfidenceBand
    read_by: str  # ocr or mixed

    def to_dict(self) -> dict[str, object]:
        data = dict(self.__dict__)
        data["band"] = self.band.value
        return data

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Stats:
    """Statistics about processing and confidence.

    Not created directly: use `VethuQ().stats`.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database

    def overview(
        self,
        group_by: StatsGroupBy | str = StatsGroupBy.SOURCE,
        *,
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
    ) -> StatsOverview:
        """The totals, and one row per group.

        `group_by` is a `StatsGroupBy`: source (the default), language, file type, engine, how the
        page was read, confidence band or day. The filters keep only matching work: `source` (id
        or path; works for removed sources too), `language`, `file_type`, `engine`, `page_source`
        (native, ocr or mixed), `band`, and `since` / `until` (UTC days, inclusive). Rows are
        sorted by `sort_by` (a `StatsSortBy`) and `order`, and paged with `limit` and `offset`;
        the total always covers every matching row. A `str` is accepted for the enums. Work done
        for a purged source is kept, under "(purged source)". Raises `ValueError` for a value
        that isn't valid and `SourceNotFoundError` for an unknown `source`.
        """
        group = StatsGroupBy(group_by) if isinstance(group_by, str) else group_by
        with self._database.session() as session:
            total, rows = _Stats.overview(
                session,
                group_by=group_by,
                source=source,
                language=language,
                file_type=file_type,
                engine=engine,
                page_source=page_source,
                band=band,
                since=since,
                until=until,
                sort_by=sort_by,
                order=order,
                limit=limit,
                offset=offset,
            )
        return StatsOverview(
            StatsRow._from_row(total), [StatsRow._from_row(r) for r in rows], group
        )

    def source(self, id_or_path: int | str | Path) -> StatsRow:
        """The totals for one source (removed sources included)."""
        return self.overview(StatsGroupBy.SOURCE, source=id_or_path).total

    def failures(
        self,
        *,
        source: int | str | Path | None = None,
        file_type: str | None = None,
        since: date | datetime | str | None = None,
        until: date | datetime | str | None = None,
    ) -> dict[str, int]:
        """How many files failed, by reason code: password, corrupt, unreadable, ocr_unavailable,
        page_too_large, language_unavailable or other."""
        with self._database.session() as session:
            return _Stats.failure_codes(
                session, source=source, file_type=file_type, since=since, until=until
            )

    def low_confidence_pages(
        self,
        *,
        source: int | str | Path | None = None,
        band: ConfidenceBand | str | None = None,
        limit: int | None = 100,
    ) -> list[LowConfidencePage]:
        """The indexed pages OCR wasn't sure of (below the `medium` band), least sure first."""
        with self._database.session() as session:
            found = _Stats.low_confidence_pages(session, source=source, band=band, limit=limit)
        return [LowConfidencePage(*item) for item in found]
