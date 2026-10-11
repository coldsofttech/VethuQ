"""What OCR is made of right now: the engines and phases the add-ons provide."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from vethuq._errors import _OcrModelMissingError
from vethuq_addon_api import (
    AddonError,
    LanguageSpec,
    OcrEngine,
    OcrEngineProvider,
    OcrPhaseSpec,
)


class _Ocr:
    """Picks the engine for a phase and language, and keeps one engine per thread.

    Building an engine loads models and an engine isn't shared between threads, so each thread
    builds its own on first use. Models are fetched automatically the first time they're needed.
    """

    PHASE = "quick"
    # After models couldn't be fetched, how long (seconds) before another attempt is made: a run
    # with many files should try once, not once per file.
    RETRY_SECONDS = 30.0
    _logger = logging.getLogger("vethuq.ocr")

    def __init__(
        self,
        providers: Callable[[], list[OcrEngineProvider]],
        phases: Callable[[], list[OcrPhaseSpec]],
        models_dir: Callable[[], Path],
        gpu: Callable[[], bool] = lambda: False,
    ) -> None:
        self.gpu = gpu
        self.providers = providers
        self.phases = phases
        self.models_dir = models_dir
        self._local = threading.local()
        self._lock = threading.Lock()
        self._ensured: set[tuple[str, str, str]] = set()
        self._failed: dict[tuple[str, str, str], tuple[float, _OcrModelMissingError]] = {}

    # ----- choosing ---------------------------------------------------------------------------

    def phase(self, phase_id: str | None = None) -> OcrPhaseSpec:
        """The OCR phase `phase_id` (default: quick). Raises `OcrModelMissingError` if no add-on
        provides it."""
        wanted = phase_id or self.PHASE
        for spec in self.phases():
            if spec.id == wanted and spec.available:
                return spec
        raise _OcrModelMissingError(
            f"OCR isn't available: the {wanted} OCR phase isn't installed.",
            f"Install the add-on: vethuq-addon-ocr-{wanted}.",
        )

    def provider(self, profile: str) -> OcrEngineProvider:
        """The first available engine that has `profile` models."""
        for provider in self.providers():
            if provider.available and profile in provider.profiles:
                return provider
        raise _OcrModelMissingError(
            "OCR isn't available: no OCR engine is installed.",
            "Install the add-on: vethuq-addon-paddle.",
        )

    # ----- engines ----------------------------------------------------------------------------

    def ensure_models(
        self, provider: OcrEngineProvider, language: LanguageSpec, profile: str
    ) -> None:
        """Download the models reading `language` needs, if any are missing."""
        key = (provider.id, language.id, profile)
        with self._lock:
            if key in self._ensured:
                return
            failure = self._failed.get(key)
            if failure is not None and time.monotonic() - failure[0] < self.RETRY_SECONDS:
                raise failure[1]
            try:
                self._ensure(provider, language, profile, key)
            except _OcrModelMissingError as exc:
                self._failed[key] = (time.monotonic(), exc)
                raise
            self._failed.pop(key, None)

    def _ensure(
        self,
        provider: OcrEngineProvider,
        language: LanguageSpec,
        profile: str,
        key: tuple[str, str, str],
    ) -> None:
        models_dir = self.models_dir()
        try:
            needed = list(provider.required_models(language, profile))
        except AddonError as exc:
            raise _OcrModelMissingError(str(exc)) from exc
        missing = [m.name for m in needed if not provider.model_path(models_dir, m.name).exists()]
        if missing:
            self._logger.info("Downloading OCR models: %s", ", ".join(missing))
            failed = provider.download(models_dir, missing)
            if failed:
                names = ", ".join(sorted(failed))
                raise _OcrModelMissingError(
                    f"Couldn't download the OCR models: {names}.",
                    "Check the internet connection, or use client.ocr.models.download().",
                )
        self._ensured.add(key)

    def engine(
        self, language: LanguageSpec, phase_id: str | None = None
    ) -> tuple[OcrEngine, OcrPhaseSpec]:
        """This thread's engine for `language` and the phase it serves (default: quick)."""
        phase = self.phase(phase_id)
        provider = self.provider(phase.profile)
        cache: dict = self._local.__dict__.setdefault("engines", {})
        use_gpu = self.gpu()
        key = (provider.id, language.id, phase.profile, use_gpu)
        engine = cache.get(key)
        if engine is None:
            self.ensure_models(provider, language, phase.profile)
            try:
                engine = provider.create(language, phase.profile, self.models_dir(), use_gpu)
            except AddonError as exc:
                if not use_gpu:
                    raise _OcrModelMissingError(f"The OCR engine couldn't start: {exc}") from exc
                self._logger.warning("The GPU can't be used (%s); reading on the CPU.", exc)
                try:
                    engine = provider.create(language, phase.profile, self.models_dir(), False)
                except AddonError as again:
                    raise _OcrModelMissingError(
                        f"The OCR engine couldn't start: {again}"
                    ) from again
            cache[key] = engine
        return engine, phase

    def prepare(self, language: LanguageSpec, phase_id: str | None = None) -> str | None:
        """Make the models ready to read `language` in the phase ahead of time. Returns why they
        can't be, or None when they are ready."""
        try:
            phase = self.phase(phase_id)
            self.ensure_models(self.provider(phase.profile), language, phase.profile)
        except _OcrModelMissingError as exc:
            return str(exc)
        return None

    def forget(self) -> None:
        """Make the next use check the models again (after they were cleared or redownloaded)."""
        with self._lock:
            self._ensured.clear()
            self._failed.clear()
