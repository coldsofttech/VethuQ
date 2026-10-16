"""The batch of anonymous, content-free statistics that metrics sharing sends."""

from __future__ import annotations

import os
import platform
import sys
import uuid
from datetime import date, timedelta
from typing import Any

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vethuq._db import _UsageDaily, _UsageEvent, _UsageFailure
from vethuq._settings import (
    _ConfidenceSettings,
    _IndexSettings,
    _LanguageSettings,
    _MetricsSettings,
)

SCHEMA_VERSION = 1
BACKLOG_DAYS = 30  # unsent days older than this are dropped rather than sent late

# The only fields a batch may hold, by object. The collector rejects anything else (see
# metrics/schema/v1/batch.schema.json, which says the same).
ALLOWED = {
    "batch": {"schema", "batch_id", "install_id", "client", "settings", "days"},
    "client": {"vethuq", "python", "os", "arch", "cpu_bucket", "ram_bucket"},
    "settings": {"workers", "retry_attempts", "languages", "confidence_bands"},
    "day": {"day", "pages", "failures", "events"},
    "event": {"kind", "engine", "query_len", "script", "results", "latency", "count"},
    "page": {
        "file_type",
        "phase",
        "language",
        "engine",
        "page_source",
        "size_bucket",
        "band",
        "pages",
        "passes",
        "duration_ms",
        "confidence_sum",
        "credits_milli",
    },  # fmt: skip
    "failure": {"file_type", "code", "count"},
}


def _bucket(value: float, edges: tuple[float, ...], labels: tuple[str, ...]) -> str:
    for edge, label in zip(edges, labels, strict=False):
        if value <= edge:
            return label
    return labels[-1]


class _Batch:
    @staticmethod
    def environment(version: str) -> dict[str, Any]:
        cores = psutil.cpu_count(logical=False) or os.cpu_count() or 1
        ram_gb = psutil.virtual_memory().total / 1024**3
        return {
            "vethuq": version,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "os": platform.system().lower() or "unknown",
            "arch": platform.machine().lower() or "unknown",
            "cpu_bucket": _bucket(cores, (2, 4, 8), ("1-2", "3-4", "5-8", "9+")),
            "ram_bucket": _bucket(ram_gb, (4.5, 9, 17, 33), ("<=4", "8", "16", "32", ">32")),
        }

    @staticmethod
    def unsent_days(session: Session, today: date) -> list[str]:
        """The closed UTC days (before today) with data that has not been sent, oldest first."""
        sent = _MetricsSettings.sent_through(session)
        days: set[str] = set()
        oldest = (today - timedelta(days=BACKLOG_DAYS)).isoformat()
        for table in (_UsageDaily, _UsageFailure, _UsageEvent):
            statement = select(table.day).where(table.day < today.isoformat()).distinct()
            statement = statement.where(table.day >= oldest)
            if sent:
                statement = statement.where(table.day > sent)
            days.update(session.scalars(statement))
        return sorted(days)

    @staticmethod
    def day_entry(session: Session, day: str) -> dict[str, Any]:
        pages = [
            {
                "file_type": r.file_type, "phase": r.phase, "language": r.language,
                "engine": r.engine[:60], "page_source": r.page_source, "size_bucket": r.size_bucket,
                "band": r.band, "pages": r.pages, "passes": r.passes,
                "duration_ms": r.duration_ms, "confidence_sum": round(r.confidence_sum, 4),
                "credits_milli": r.credits_milli,
            }  # fmt: skip
            for r in session.execute(
                select(
                    _UsageDaily.file_type, _UsageDaily.phase, _UsageDaily.language,
                    _UsageDaily.engine, _UsageDaily.page_source, _UsageDaily.size_bucket,
                    _UsageDaily.band, func.sum(_UsageDaily.pages).label("pages"),
                    func.sum(_UsageDaily.passes).label("passes"),
                    func.sum(_UsageDaily.duration_ms).label("duration_ms"),
                    func.sum(_UsageDaily.confidence_sum).label("confidence_sum"),
                    func.sum(_UsageDaily.credits_milli).label("credits_milli"),
                )
                .where(_UsageDaily.day == day)
                .group_by(
                    _UsageDaily.file_type, _UsageDaily.phase, _UsageDaily.language,
                    _UsageDaily.engine, _UsageDaily.page_source, _UsageDaily.size_bucket,
                    _UsageDaily.band,
                )
                .order_by(_UsageDaily.file_type, _UsageDaily.language, _UsageDaily.page_source)
            )
        ]  # fmt: skip
        failures = [
            {"file_type": ft, "code": code, "count": int(n)}
            for ft, code, n in session.execute(
                select(_UsageFailure.file_type, _UsageFailure.code, func.sum(_UsageFailure.count))
                .where(_UsageFailure.day == day)
                .group_by(_UsageFailure.file_type, _UsageFailure.code)
                .order_by(_UsageFailure.file_type, _UsageFailure.code)
            )
        ]
        events = [
            {"kind": r.kind, "engine": r.engine, "query_len": r.query_len, "script": r.script,
             "results": r.results, "latency": r.latency, "count": int(r.count)}
            for r in session.execute(
                select(
                    _UsageEvent.kind, _UsageEvent.engine, _UsageEvent.query_len,
                    _UsageEvent.script, _UsageEvent.results, _UsageEvent.latency,
                    func.sum(_UsageEvent.count).label("count"),
                )
                .where(_UsageEvent.day == day)
                .group_by(_UsageEvent.kind, _UsageEvent.engine, _UsageEvent.query_len,
                          _UsageEvent.script, _UsageEvent.results, _UsageEvent.latency)
                .order_by(_UsageEvent.kind, _UsageEvent.engine)
            )
        ]  # fmt: skip
        entry: dict[str, Any] = {"day": day, "pages": pages, "failures": failures}
        if events:
            entry["events"] = events
        return entry

    @staticmethod
    def build(
        session: Session, today: date, version: str, max_bytes: int
    ) -> tuple[dict[str, Any], str | None]:
        """The next batch: the oldest unsent closed days that fit in `max_bytes`. Also the last
        day it holds (None when there is nothing to send, which is a heartbeat)."""
        import json  # noqa: PLC0415

        batch: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "batch_id": uuid.uuid4().hex,
            "install_id": _MetricsSettings.install_id(session),
            "client": _Batch.environment(version),
            "settings": {
                "workers": _IndexSettings.get_workers(session),
                "retry_attempts": _IndexSettings.get_retry_attempts(session),
                "languages": _LanguageSettings.get_default(session) or ["en"],
                "confidence_bands": list(_ConfidenceSettings.get_bands(session)),
            },
            "days": [],
        }
        last = None
        for day in _Batch.unsent_days(session, today):
            batch["days"].append(_Batch.day_entry(session, day))
            if len(json.dumps(batch).encode()) > max_bytes:
                if len(batch["days"]) == 1:
                    batch["days"][0]["pages"] = batch["days"][0]["pages"][:50]  # a huge day
                else:
                    batch["days"].pop()
                    break
            last = day
        return batch, last

    @staticmethod
    def check(batch: dict[str, Any]) -> None:
        """Refuse a batch with any field that isn't on the list. Raises `ValueError`."""

        def walk(kind: str, value: dict[str, Any]) -> None:
            extra = set(value) - ALLOWED[kind]
            if extra:
                raise ValueError(f"unexpected field(s) in {kind}: {sorted(extra)}")

        walk("batch", batch)
        walk("client", batch["client"])
        walk("settings", batch["settings"])
        for day in batch["days"]:
            walk("day", day)
            for page in day["pages"]:
                walk("page", page)
            for failure in day["failures"]:
                walk("failure", failure)
            for event in day.get("events", []):
                walk("event", event)
