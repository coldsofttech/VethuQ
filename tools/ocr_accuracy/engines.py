"""The reader for the real engine: VethuQ's own OCR runtime, with its add-ons and models.

It uses the runtime the way indexing does: the engine and angles come from the OCR phase, and a
later phase reads the angles of the earlier ones too (the moderate phase turns a page upright, the
deep one tries the angles in between), keeping the read with the highest confidence. Models are
fetched on first use, so this needs the network the first time. It reaches into the client's OCR
runtime (`_runtime()`), which is private: this is a test tool that lives with the core.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tools.ocr_accuracy.suite import Reading


class ClientReader:
    def __init__(self, client: Any) -> None:
        self._manager = client._manager()
        self._runtime = client._runtime()

    def phases(self) -> list[str]:
        """The OCR phases that can run here, in the order they run."""
        return [p.id for p in sorted(self._runtime.phases(), key=lambda p: p.order) if p.available]

    def _language(self, language: str) -> Any:
        for spec in self._manager.language_specs():
            if spec.id == language and spec.available:
                return spec
        raise LookupError(f"The {language!r} language isn't available here.")

    def _angles(self, phase: str) -> list[int]:
        """The angles read by `phase` and every phase before it."""
        angles: list[int] = []
        for spec in sorted(self._runtime.phases(), key=lambda p: p.order):
            angles.extend(a for a in spec.angles if a not in angles)
            if spec.id == phase:
                break
        return angles

    def read(self, image: np.ndarray, phase: str, language: str) -> Reading:
        engine, _ = self._runtime.engine(self._language(language), phase)
        results = [engine.recognize(image, angle) for angle in self._angles(phase)]
        best = max(results, key=lambda r: r.confidence)
        return Reading(best.text, best.confidence)
