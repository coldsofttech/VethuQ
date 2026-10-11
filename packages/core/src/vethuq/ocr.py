"""OCR: the engines, phases and models behind reading scanned pages: `VethuQ().ocr`.

OCR comes from add-ons: an engine (`vethuq-addon-paddle`) and its phases (`vethuq-addon-ocr-quick`).
Models are fetched automatically the first time they're needed; `ocr.models` lets you see them,
fetch them ahead of time, and clean up.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from vethuq._errors import _OcrModelMissingError
from vethuq._ocr import _ModelInfo, _Models, _Ocr
from vethuq_addon_api import OcrEngineProvider, OcrPhaseSpec

__all__ = ["Ocr", "OcrEngine", "OcrEngines", "OcrModel", "OcrModels", "OcrPhase", "OcrPhases"]

# Called with (model name, state) where state is "downloading", "ready" or "failed".
ProgressCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class OcrEngine:
    """An OCR engine."""

    id: str
    label: str
    profiles: tuple[str, ...]  # the model sets it offers, e.g. ("mobile",)
    available: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "profiles": list(self.profiles),
            "available": self.available,
            "reason": self.reason,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class OcrPhase:
    """A phase of OCR: how pages are read, in order from the fastest."""

    id: str  # for example "quick"
    label: str
    order: int
    angles: tuple[int, ...]  # the rotations it reads, in degrees
    profile: str  # the model set it uses, e.g. "mobile"
    available: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "order": self.order,
            "angles": list(self.angles),
            "profile": self.profile,
            "available": self.available,
            "reason": self.reason,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass(frozen=True)
class OcrModel:
    """A model an OCR engine needs."""

    name: str
    engine: str  # the engine's id
    kind: str  # for example "detection" or "recognition"
    shared: bool  # used by every language
    languages: tuple[str, ...]  # the languages that need it
    installed: bool
    path: str
    size_bytes: int  # on disk; 0 when not installed

    @classmethod
    def _from_info(cls, info: _ModelInfo) -> OcrModel:
        return cls(**info.__dict__)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "engine": self.engine,
            "kind": self.kind,
            "shared": self.shared,
            "languages": list(self.languages),
            "installed": self.installed,
            "path": self.path,
            "size_bytes": self.size_bytes,
        }

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class OcrEngines:
    """The OCR engines installed. Use `VethuQ().ocr.engines`."""

    def __init__(self, providers: Callable[[], list[OcrEngineProvider]]) -> None:
        self._providers = providers

    def list(self) -> list[OcrEngine]:
        """Every OCR engine the installed add-ons provide, by id."""
        return [
            OcrEngine(
                p.id, p.label, tuple(p.profiles), p.available, "" if p.available else p.reason
            )
            for p in self._providers()
        ]


class OcrPhases:
    """The OCR phases installed. Use `VethuQ().ocr.phases`."""

    def __init__(self, phases: Callable[[], list[OcrPhaseSpec]]) -> None:
        self._phases = phases

    def list(self) -> list[OcrPhase]:
        """Every OCR phase the installed add-ons provide, in the order they run."""
        return [
            OcrPhase(
                s.id,
                s.label,
                s.order,
                tuple(s.angles),
                s.profile,
                s.available,
                "" if s.available else s.reason,
            )
            for s in self._phases()
        ]


class OcrModels:
    """The OCR models on disk. Use `VethuQ().ocr.models`.

    `languages` is a list of language ids; left out, every language is meant.
    """

    def __init__(self, models: _Models, models_dir: Callable[[], Path]) -> None:
        self._models = models
        self._models_dir = models_dir

    @property
    def cache_dir(self) -> Path:
        """The folder the models are kept in."""
        return self._models_dir()

    def list(self, languages: Sequence[str] | None = None) -> list[OcrModel]:
        """The models the installed languages need, and whether each is on disk.

        Raises `InvalidSettingValueError` for an unknown language.
        """
        return [OcrModel._from_info(i) for i in self._models.list(languages)]

    @staticmethod
    def _check(failures: list[str]) -> None:
        if failures:
            raise _OcrModelMissingError(
                f"Couldn't download: {'; '.join(failures)}.",
                "Check the internet connection and try again.",
            )

    def download(
        self, languages: Sequence[str] | None = None, on_progress: ProgressCallback | None = None
    ) -> list[OcrModel]:
        """Download the models that are missing and return the models. Reading downloads them
        automatically, so this is only to do it ahead of time.

        Raises `OcrModelMissingError` if any couldn't be downloaded.
        """
        self._check(self._models.download(languages, on_progress))
        return self.list(languages)

    def redownload(
        self, names: Sequence[str] | None = None, languages: Sequence[str] | None = None
    ) -> list[OcrModel]:
        """Delete and download again the models called `names` (all, if left out) among those the
        languages need. Raises `OcrModelMissingError` if any couldn't be downloaded."""
        self._check(self._models.redownload(names, languages))
        return self.list(languages)

    def clear(self, languages: Sequence[str], include_shared: bool = False) -> list[str]:
        """Delete the models only `languages` use, and return their names. Models shared by every
        language, or still used by another, are kept unless `include_shared`."""
        return self._models.clear(languages, include_shared)

    def clean(self) -> list[str]:
        """Delete models no installed language needs any more and return their names."""
        return self._models.clean()


class Ocr:
    """OCR engines, phases and models.

    Not created directly: use `VethuQ().ocr`.
    """

    def __init__(self, runtime: _Ocr, models: _Models) -> None:
        self.engines = OcrEngines(runtime.providers)
        self.phases = OcrPhases(runtime.phases)
        self.models = OcrModels(models, runtime.models_dir)
