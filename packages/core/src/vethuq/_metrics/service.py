"""Sharing the batch: when it is allowed, sending it, and what comes of it."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from vethuq._credits import _Clock, _Credits
from vethuq._db import _Database
from vethuq._metrics.batch import _Batch
from vethuq._settings import _MetricsSettings, _Settings

_logger = logging.getLogger("vethuq.metrics")
LAST_ATTEMPT_KEY = "metrics_last_attempt_on"


@dataclass(frozen=True)
class _Outcome:
    status: str  # sent, not_opted_in, disabled, nothing_to_do, failed
    days: int = 0
    size_bytes: int = 0
    detail: str = ""


def post(url: str, body: bytes, timeout: float = 10.0) -> tuple[int, str]:
    """POST JSON. Replaced in tests."""
    if not url.lower().startswith("https://"):
        raise ValueError("metrics are only sent over https")
    request = urllib.request.Request(  # noqa: S310 - https only, checked above
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read(2048).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2048).decode("utf-8", "replace")


class _Metrics:
    def __init__(
        self,
        database: _Database,
        credits: _Credits,
        version: str,
        sender: Callable[[str, bytes], tuple[int, str]] | None = None,
    ) -> None:
        self.database = database
        self.credits = credits
        self.version = version
        self.sender = sender or post

    # ----- policy -----------------------------------------------------------------------------

    def terms(self, session: Session):
        return self.credits.terms(session)

    def collector(self, session: Session) -> str | None:
        """The collector's base URL if the policy lets metrics be sent."""
        terms = self.terms(session)
        endpoint = terms.metrics_endpoint.rstrip("/")
        if not terms.metrics_enabled or not endpoint.lower().startswith("https://"):
            return None
        return endpoint

    # ----- status -----------------------------------------------------------------------------

    def status(self, session: Session) -> dict[str, Any]:
        terms = self.terms(session)
        today = _Clock.today(session)
        return {
            "opted_in": _MetricsSettings.get_opt_in(session),
            "available": self.collector(session) is not None,
            "last_sent_at": _Settings.get(session, _MetricsSettings.LAST_SENT_KEY),
            "sent_through": _MetricsSettings.sent_through(session),
            "bonus_active": _Credits.bonus_active(session, today),
            "bonus_percent": min(terms.bonus_percent, terms.bonus_cap_percent),
            "pending_days": len(_Batch.unsent_days(session, today)),
        }

    def preview(self, session: Session) -> tuple[dict[str, Any], str | None]:
        terms = self.terms(session)
        return _Batch.build(
            session, _Clock.today(session), self.version, terms.metrics_max_batch_bytes
        )

    # ----- sending ----------------------------------------------------------------------------

    def send(self, *, force: bool = False) -> _Outcome:
        """Send the next batch if sharing is on and allowed. Never raises. Without `force` it
        tries at most once per UTC day."""
        try:
            return self._send(force)
        except Exception as exc:  # noqa: BLE001 - sharing never gets in the way of work
            _logger.warning("Sending metrics failed", exc_info=True)
            return _Outcome("failed", detail=f"{type(exc).__name__}: {exc}")

    def _send(self, force: bool) -> _Outcome:
        with self.database.session() as session:
            if not _MetricsSettings.get_opt_in(session):
                return _Outcome("not_opted_in")
            base = self.collector(session)
            if base is None:
                return _Outcome("disabled", detail="the policy doesn't allow sending right now")
            today = _Clock.today(session)
            if not force and _Settings.get(session, LAST_ATTEMPT_KEY) == today.isoformat():
                return _Outcome("nothing_to_do", detail="already tried today")
            _Settings.set(session, LAST_ATTEMPT_KEY, today.isoformat())
            batch, last = self.preview(session)
        _Batch.check(batch)
        body = json.dumps(batch, separators=(",", ":")).encode("utf-8")
        try:
            status, text = self.sender(f"{base}/v1/batch", body)
        except Exception as exc:  # noqa: BLE001
            return _Outcome("failed", detail=f"{type(exc).__name__}: {exc}")
        if not 200 <= status < 300:
            return _Outcome("failed", detail=f"the collector answered {status}: {text[:200]}")
        with self.database.session() as session:
            _Settings.set(session, _MetricsSettings.LAST_SENT_KEY, _Clock.now(session).isoformat())
            if last:
                _Settings.set(session, _MetricsSettings.SENT_THROUGH_KEY, last)
        return _Outcome("sent", days=len(batch["days"]), size_bytes=len(body))

    def delete_data(self) -> _Outcome:
        """Ask the collector to delete everything it holds for this install, then start with a
        new id. Raises nothing; `failed` says why it couldn't."""
        try:
            with self.database.session() as session:
                base = self.collector(session)
                install = _MetricsSettings.install_id(session)
            if base is None:
                return _Outcome("disabled", detail="no collector is available")
            body = json.dumps({"install_id": install}).encode("utf-8")
            status, text = self.sender(f"{base}/v1/delete", body)
            if not 200 <= status < 300:
                return _Outcome("failed", detail=f"the collector answered {status}: {text[:200]}")
            with self.database.session() as session:
                _MetricsSettings.new_install_id(session)
                _Settings.reset(session, _MetricsSettings.SENT_THROUGH_KEY)
                _Settings.reset(session, _MetricsSettings.LAST_SENT_KEY)
            return _Outcome("sent")
        except Exception as exc:  # noqa: BLE001
            return _Outcome("failed", detail=f"{type(exc).__name__}: {exc}")
