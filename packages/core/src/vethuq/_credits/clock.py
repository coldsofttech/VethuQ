"""The UTC day credits reset on. Time never goes backwards: if the computer's clock is set back,
the latest time seen is used, so the daily allowance can't be collected twice."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from vethuq._settings import _Settings


class _Clock:
    KEY = "credits_clock_high"
    # Replaced in tests.
    system = staticmethod(lambda: datetime.now(UTC))
    _lock = threading.Lock()

    @staticmethod
    def now(session: Session) -> datetime:
        with _Clock._lock:
            moment = _Clock.system()
            stored = _Settings.get(session, _Clock.KEY)
            high = None
            if stored:
                try:
                    high = datetime.fromisoformat(stored)
                except ValueError:
                    high = None
            if high is not None and high > moment:
                return high
            if high is None or (moment - high).total_seconds() > 60:
                _Settings.set(session, _Clock.KEY, moment.isoformat())
            return moment

    @staticmethod
    def today(session: Session) -> date:
        return _Clock.now(session).date()
