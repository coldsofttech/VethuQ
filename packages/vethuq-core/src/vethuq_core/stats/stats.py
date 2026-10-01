"""Operations across both the processing and confidence statistics."""

from __future__ import annotations

import sqlite3

from vethuq_core.stats.confidence import Confidence
from vethuq_core.stats.processing import Processing


class Stats:
    @staticmethod
    def reset(conn: sqlite3.Connection) -> None:
        """Clear `processing_metrics` and `confidence_metrics`.

        Both are running averages folded in per file/page as OCR completes, and
        `vethuq index run` reads `processing_metrics` for its ETA estimate -
        clearing them makes that estimate unavailable again until enough newly
        (re)indexed files have rebuilt the averages.
        """
        Processing.clear(conn)
        Confidence.clear(conn)
        conn.commit()
