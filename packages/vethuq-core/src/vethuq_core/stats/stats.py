"""Operations across both the processing and confidence statistics."""

from __future__ import annotations

from vethuq_core.stats.confidence import Confidence
from vethuq_core.stats.processing import Processing
from vethuq_core.storage import Storage


class Stats:
    @staticmethod
    def reset(storage: Storage) -> None:
        """Clear `processing_metrics` and `confidence_metrics`.

        Both are running averages folded in per file/page as OCR completes, and
        `vethuq index run` reads `processing_metrics` for its ETA estimate -
        clearing them makes that estimate unavailable again until enough newly
        (re)indexed files have rebuilt the averages.
        """
        Processing.clear(storage)
        Confidence.clear(storage)
        storage.commit()
