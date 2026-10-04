"""Engine registry: which `OcrEngine` implementations exist and how they're built.

Concrete engines are imported lazily inside their factory, so nothing heavy
loads until an engine is actually asked for (PDFs whose text is fully native
never construct one at all), and `vethuq_core.ocr` never imports one directly.
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable

from vethuq_core.ocr.catalog import OcrCatalog, OcrComponentInfo
from vethuq_core.ocr.engines.base import OcrEngine
from vethuq_core.settings import GpuSettings
from vethuq_core.storage import Storage

# Builds an engine; the flag is the user's GPU setting (engines that can't use a GPU ignore it).
# A factory may take the language to build it for as a second argument; one that doesn't is an
# engine for the default language only.
EngineFactory = Callable[..., OcrEngine]


class Engines:
    DEFAULT = "paddleocr"

    _factories: dict[str, EngineFactory] = {}

    # Engine construction (model loading) is expensive; share one engine per
    # *thread* and language rather than per process - a run with N worker threads (see
    # `Scheduler.resolve_workers`) gets N engine instances per language so OCR inference itself
    # actually parallelizes, at the cost of N times the model memory footprint. Constructed
    # lazily on first use in each thread, so a language that no file needs is never loaded.
    _local = threading.local()

    @staticmethod
    def register(name: str, factory: EngineFactory) -> None:
        """Make an engine available under `name`, replacing any existing one."""
        Engines._factories[name] = factory

    @staticmethod
    def _paddleocr_factory(use_gpu: bool, language: OcrComponentInfo) -> OcrEngine:
        from vethuq_core.ocr.engines.paddle import PaddleOcrEngine

        if language.default or not language.paddle_lang:
            return PaddleOcrEngine(use_gpu=use_gpu)
        return PaddleOcrEngine(use_gpu=use_gpu, language=language.paddle_lang)

    @staticmethod
    def get(storage: Storage, language: str | None = None) -> OcrEngine:
        """Return the calling thread's engine for `language` (a language id such as `te`; the
        default language when left out), constructing it on first use.

        Engine choice is fixed to `DEFAULT` for now - selecting between
        engines is out of scope until more than one is supported.
        """
        info = OcrCatalog.language(language) if language else OcrCatalog.default_language()
        if info is None:
            raise ValueError(f"Unknown OCR language {language!r}")
        engines: dict[tuple[str, str], OcrEngine] | None = getattr(Engines._local, "engines", None)
        if engines is None:
            engines = Engines._local.engines = {}
        key = (Engines.DEFAULT, info.id)
        engine = engines.get(key)
        if engine is None:
            engine = engines[key] = Engines._build(
                Engines._factories[Engines.DEFAULT], GpuSettings.is_enabled(storage), info
            )
        return engine

    @staticmethod
    def _build(factory: EngineFactory, use_gpu: bool, language: OcrComponentInfo) -> OcrEngine:
        if len(inspect.signature(factory).parameters) >= 2:
            return factory(use_gpu, language)
        if not language.default:
            raise ValueError(f"The OCR engine has no support for the {language.label} language")
        return factory(use_gpu)


Engines.register(Engines.DEFAULT, Engines._paddleocr_factory)
