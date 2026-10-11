"""What OCR is made of right now: the engines and phases the add-ons provide."""

from __future__ import annotations

import logging
import threading
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
    _logger = logging.getLogger("vethuq.ocr")

    def __init__(
        self,
        providers: Callable[[], list[OcrEngineProvider]],
        phases: Callable[[], list[OcrPhaseSpec]],
        models_dir: Callable[[], Path],
    ) -> None:
        self.providers = providers
        self.phases = phases
        self.models_dir = models_dir
        self._local = threading.local()
        self._lock = threading.Lock()
        self._ensured: set[tuple[str, str, str]] = set()

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
            models_dir = self.models_dir()
            try:
                needed = list(provider.required_models(language, profile))
            except AddonError as exc:
                raise _OcrModelMissingError(str(exc)) from exc
            missing = [
                m.name for m in needed if not provider.model_path(models_dir, m.name).exists()
            ]
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
        key = (provider.id, language.id, phase.profile)
        engine = cache.get(key)
        if engine is None:
            self.ensure_models(provider, language, phase.profile)
            try:
                engine = provider.create(language, phase.profile, self.models_dir())
            except AddonError as exc:
                raise _OcrModelMissingError(f"The OCR engine couldn't start: {exc}") from exc
            cache[key] = engine
        return engine, phase

    def forget(self) -> None:
        """Make the next use check the models again (after they were cleared or redownloaded)."""
        with self._lock:
            self._ensured.clear()
