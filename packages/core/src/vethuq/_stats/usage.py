"""Recording what was processed: the daily totals statistics and metrics are built from."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vethuq._db import _UsageDaily, _UsageFailure
from vethuq.enums import ConfidenceBand


class _ErrorCode:
    """Why a file failed, as a short code (never the message, which can hold a path)."""

    PASSWORD = "password"  # noqa: S105 - a reason code, not a secret
    CORRUPT = "corrupt"
    UNREADABLE = "unreadable"
    OCR_UNAVAILABLE = "ocr_unavailable"
    PAGE_TOO_LARGE = "page_too_large"
    LANGUAGE = "language_unavailable"
    OTHER = "other"


class _Bands:
    @staticmethod
    def of(confidence: float, bands: tuple[int, int, int]) -> ConfidenceBand:
        """The band for a confidence from 0 to 1, given where low, medium and high start (%)."""
        low, medium, high = bands
        percent = confidence * 100
        if percent >= high:
            return ConfidenceBand.HIGH
        if percent >= medium:
            return ConfidenceBand.MEDIUM
        if percent >= low:
            return ConfidenceBand.LOW
        return ConfidenceBand.UNRELIABLE


@dataclass(frozen=True)
class _PageFact:
    """What one page read amounts to, for the daily totals."""

    page_source: str  # native, ocr, mixed
    phase: str  # "" for a native page
    engine: str
    size_bucket: str
    confidence: float
    duration_ms: int
    credits_milli: int
    passes: int


class _Usage:
    @staticmethod
    def record_pages(
        session: Session,
        day: str,
        source_id: int | None,
        file_type: str,
        language: str,
        facts: list[_PageFact],
        bands: tuple[int, int, int],
    ) -> None:
        totals: dict[tuple, list[float]] = defaultdict(lambda: [0, 0, 0, 0.0, 0])
        for fact in facts:
            key = (
                fact.phase,
                fact.engine,
                fact.page_source,
                fact.size_bucket,
                _Bands.of(fact.confidence, bands).value,
            )
            row = totals[key]
            row[0] += 1
            row[1] += fact.passes
            row[2] += fact.duration_ms
            row[3] += fact.confidence
            row[4] += fact.credits_milli
        for (phase, engine, page_source, bucket, band), (
            pages,
            passes,
            ms,
            conf,
            credits,
        ) in totals.items():
            row = session.scalars(
                select(_UsageDaily).where(
                    _UsageDaily.day == day,
                    func.coalesce(_UsageDaily.source_id, 0) == (source_id or 0),
                    _UsageDaily.file_type == file_type,
                    _UsageDaily.phase == phase,
                    _UsageDaily.language == language,
                    _UsageDaily.engine == engine,
                    _UsageDaily.page_source == page_source,
                    _UsageDaily.size_bucket == bucket,
                    _UsageDaily.band == band,
                )
            ).first()
            if row is None:
                row = _UsageDaily(
                    day=day,
                    source_id=source_id,
                    file_type=file_type,
                    phase=phase,
                    language=language,
                    engine=engine,
                    page_source=page_source,
                    size_bucket=bucket,
                    band=band,
                    pages=0,
                    passes=0,
                    duration_ms=0,
                    confidence_sum=0.0,
                    credits_milli=0,
                )
                session.add(row)
            row.pages += int(pages)
            row.passes += int(passes)
            row.duration_ms += int(ms)
            row.confidence_sum += conf
            row.credits_milli += int(credits)
        session.flush()

    @staticmethod
    def record_failure(
        session: Session, day: str, source_id: int | None, file_type: str, code: str
    ) -> None:
        row = session.scalars(
            select(_UsageFailure).where(
                _UsageFailure.day == day,
                func.coalesce(_UsageFailure.source_id, 0) == (source_id or 0),
                _UsageFailure.file_type == file_type,
                _UsageFailure.code == code,
            )
        ).first()
        if row is None:
            row = _UsageFailure(
                day=day, source_id=source_id, file_type=file_type, code=code, count=0
            )
            session.add(row)
        row.count += 1
        session.flush()
