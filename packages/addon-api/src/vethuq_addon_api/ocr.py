"""OCR engines: what VethuQ needs from "an engine that recognizes text in an image"."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vethuq_addon_api.api import LanguageSpec


@dataclass(frozen=True)
class OcrResult:
    """What one engine call recognized in one image.

    `engine` and `language` describe what produced it. `image_width` / `image_height` are the
    recognized image's size in pixels, or None. `lines` are the recognized lines with their own
    confidence, for callers that filter line by line.
    """

    text: str
    confidence: float
    engine: str
    language: str
    image_width: int | None = None
    image_height: int | None = None
    lines: tuple[tuple[str, float], ...] = ()


class OcrEngine(Protocol):
    """Recognizes the text in an image. An instance is only ever used from the thread that
    created it, so `recognize` needn't be thread-safe; building one may be expensive (loading
    models), so do that in `__init__`."""

    @property
    def name(self) -> str:
        """The engine's label with its version, for example `paddleocr 3.0.1`."""
        ...

    @property
    def language(self) -> str:
        """The language id the engine reads."""
        ...

    def recognize(self, image: Any, angle: int = 0) -> OcrResult:
        """Recognize the text in `image`: an image file path or a BGR pixel array. `angle` turns
        the image counter-clockwise by that many degrees first (0 reads it as it is)."""
        ...


@dataclass(frozen=True)
class OcrModelSpec:
    """One model file set an engine needs. `shared` models serve every language."""

    name: str
    kind: str = ""  # for example "detection", "recognition", "orientation"
    shared: bool = False


# Called with (model name, state) where state is "downloading", "ready" or "failed".
ModelProgress = Callable[[str, str], None]


class OcrEngineProvider(ABC):
    """An OCR engine an add-on provides, and the models it needs.

    `profiles` are the model sets it offers (for example `mobile`); an OCR phase asks for one.
    Models live under the `models_dir` VethuQ passes in, so VethuQ can list, download and clean
    them without knowing the engine.
    """

    id: str
    label: str
    profiles: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """Whether the engine can be used now."""
        return True

    @property
    def reason(self) -> str:
        """Why it isn't available, when it isn't."""
        return ""

    @abstractmethod
    def create(
        self, language: LanguageSpec, profile: str, models_dir: Path, use_gpu: bool = False
    ) -> OcrEngine:
        """Build an engine for `language` with the `profile` models. Raise `AddonError` if the
        engine or its models can't be loaded."""

    @abstractmethod
    def required_models(self, language: LanguageSpec, profile: str) -> Sequence[OcrModelSpec]:
        """Every model reading `language` with `profile` needs."""

    @abstractmethod
    def known_models(self, languages: Sequence[LanguageSpec]) -> Sequence[OcrModelSpec]:
        """Every model this engine could use for `languages`, across all its profiles."""

    @abstractmethod
    def model_path(self, models_dir: Path, name: str) -> Path:
        """Where model `name` is kept (a folder or a file)."""

    @abstractmethod
    def download(
        self, models_dir: Path, names: Sequence[str], on_progress: ModelProgress | None = None
    ) -> dict[str, str]:
        """Download the models. Returns `{name: error}` for the ones that failed (empty if all
        arrived)."""
