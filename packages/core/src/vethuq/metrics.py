"""Sharing anonymous usage metrics: `VethuQ().metrics`.

Off unless you turn it on. When on, aggregated statistics about OCR (timings, confidence, phases,
languages, engine, settings, failure reasons, size buckets and rough hardware) are sent to the
collector the policy names. Never file names, paths, content, OCR text, search text, user names,
licence ids or anything derived from your computer. In return the daily credits of the local
wallet go up (10% by default) while sharing is on and a batch was sent in the last 7 days.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vethuq._db import _Database
from vethuq._metrics import _Metrics
from vethuq._settings import _MetricsSettings

__all__ = ["Metrics", "MetricsBatch", "MetricsSendResult", "MetricsStatus"]


@dataclass(frozen=True)
class MetricsStatus:
    """Where metrics sharing stands."""

    opted_in: bool
    available: bool  # the policy allows sending and names a collector
    last_sent_at: str | None  # UTC, ISO 8601
    sent_through: str | None  # the last UTC day whose data was sent
    pending_days: int  # closed days still to send
    bonus_active: bool  # the credits bonus is on today
    bonus_percent: float  # what it would be

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class MetricsBatch:
    """What would be sent next, exactly."""

    data: dict[str, object]
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return dict(self.data)

    def to_json(self, indent: int | None = None) -> str:
        """The batch as a JSON string."""
        return json.dumps(self.data, indent=indent)


@dataclass(frozen=True)
class MetricsSendResult:
    """What a send did. `status` is `sent`, `not_opted_in`, `disabled` (the policy doesn't allow
    it), `nothing_to_do` (already tried today) or `failed` (see `detail`)."""

    status: str
    days: int = 0
    size_bytes: int = 0
    detail: str = ""

    @property
    def sent(self) -> bool:
        return self.status == "sent"

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Metrics:
    """Opt in or out, preview and send metrics, and delete what was sent.

    Not created directly: use `VethuQ().metrics`.
    """

    def __init__(self, database: _Database, metrics: _Metrics) -> None:
        self._database = database
        self._metrics = metrics

    def status(self) -> MetricsStatus:
        with self._database.session() as session:
            return MetricsStatus(**self._metrics.status(session))

    def opt_in(self) -> MetricsStatus:
        """Turn sharing on. The credits bonus starts the UTC day after the first batch is sent."""
        with self._database.session() as session:
            _MetricsSettings.set_opt_in(session, True)
        return self.status()

    def opt_out(self) -> MetricsStatus:
        """Turn sharing off (and the bonus with it). Data already sent stays until you ask for it
        to be deleted with `delete_data()`."""
        with self._database.session() as session:
            _MetricsSettings.set_opt_in(session, False)
        return self.status()

    def preview(self) -> MetricsBatch:
        """The batch that would be sent next, exactly as it would be sent."""
        with self._database.session() as session:
            batch, _last = self._metrics.preview(session)
        return MetricsBatch(batch, len(json.dumps(batch, separators=(",", ":")).encode()))

    def send(self, force: bool = False) -> MetricsSendResult:
        """Send the next batch now, if sharing is on and the policy allows it. It never raises.
        Without `force` it tries at most once per UTC day (an index run does this at its end)."""
        outcome = self._metrics.send(force=force)
        return MetricsSendResult(outcome.status, outcome.days, outcome.size_bytes, outcome.detail)

    def delete_data(self) -> MetricsSendResult:
        """Ask the collector to delete everything it holds for this install, and start with a new
        anonymous id. Sharing stays as it was."""
        outcome = self._metrics.delete_data()
        return MetricsSendResult(outcome.status, detail=outcome.detail)
