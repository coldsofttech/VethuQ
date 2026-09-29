"""Engine registry: which `OcrEngine` implementations exist and how they're built.

Concrete engines are imported lazily inside their factory, so nothing heavy
loads until an engine is actually asked for (PDFs whose text is fully native
never construct one at all), and `vethuq_core.ocr` never imports one directly.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

from vethuq_core.ocr.engines.base import OcrEngine
from vethuq_core.settings import GpuSettings

# Builds an engine; the flag is the user's GPU setting (engines that can't use
# a GPU ignore it).
EngineFactory = Callable[[bool], OcrEngine]


class Engines:
    DEFAULT = "paddleocr"

    _factories: dict[str, EngineFactory] = {}

    # Engine construction (model loading) is expensive; share one engine per
    # *thread* rather than per process - a run with N worker threads (see
    # `Scheduler.resolve_workers`) gets N engine instances so OCR inference itself
    # actually parallelizes, at the cost of N times the model memory footprint.
    # Constructed lazily on first use in each thread.
    _local = threading.local()

    @staticmethod
    def register(name: str, factory: EngineFactory) -> None:
        """Make an engine available under `name`, replacing any existing one."""
        Engines._factories[name] = factory

    @staticmethod
    def _paddleocr_factory(use_gpu: bool) -> OcrEngine:
        from vethuq_core.ocr.engines.paddle import PaddleOcrEngine

        return PaddleOcrEngine(use_gpu=use_gpu)

    @staticmethod
    def get(conn: sqlite3.Connection) -> OcrEngine:
        """Return the calling thread's engine, constructing it on first use.

        Engine choice is fixed to `DEFAULT` for now - selecting between
        engines is out of scope until more than one is supported.
        """
        engines: dict[str, OcrEngine] | None = getattr(Engines._local, "engines", None)
        if engines is None:
            engines = Engines._local.engines = {}
        engine = engines.get(Engines.DEFAULT)
        if engine is None:
            engine = engines[Engines.DEFAULT] = Engines._factories[Engines.DEFAULT](
                GpuSettings.is_enabled(conn)
            )
        return engine


Engines.register(Engines.DEFAULT, Engines._paddleocr_factory)
