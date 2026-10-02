"""The OCR-engine interface: what `vethuq_core.ocr` needs from "an OCR engine".

Orchestration (`vethuq_core.ocr`) depends only on this module and
`vethuq_core.ocr.engines.registry`, never on a concrete engine, so adding an
engine means adding one `OcrEngine` implementation and registering it - the
storage layer (`document_index`/`pdf_pages`/`image_pages`) only ever sees the
plain values an `OcrResult` carries, so it stays engine-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class OcrResult:
    """What one engine call recognized in one image.

    `engine` and `language` describe the engine that produced it (stored
    alongside the text as `ocr_engine`/`language`). `image_width`/
    `image_height` are the recognized image's pixel size, or None if the
    engine couldn't determine it. `lines` are the individual recognized lines
    with their own confidence, for callers that filter line by line.
    """

    text: str
    confidence: float
    engine: str
    language: str
    image_width: int | None = None
    image_height: int | None = None
    lines: tuple[tuple[str, float], ...] = ()


class OcrEngine(Protocol):
    """Recognizes the text in an image. Implement this to add a new OCR engine.

    An instance is only ever used from the thread that created it (see
    `vethuq_core.ocr.engines.registry.Engines.get`), so `recognize` doesn't
    need to be thread-safe - but constructing one may be expensive (model
    loading), so build it in `__init__` rather than per `recognize` call.
    """

    @property
    def name(self) -> str:
        """Engine label with its version, e.g. `paddleocr 3.0.1`."""
        ...

    @property
    def language(self) -> str:
        """Language the engine is configured to recognize, e.g. `en`."""
        ...

    def recognize(self, image: str | np.ndarray) -> OcrResult:
        """Recognize the text in `image` - an image file path or a BGR pixel array."""
        ...
