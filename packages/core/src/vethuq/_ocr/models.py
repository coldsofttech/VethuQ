"""The OCR models on disk: which there are, and fetching, clearing and cleaning them."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from vethuq._errors import _InvalidSettingValueError
from vethuq_addon_api import LanguageSpec, ModelProgress, OcrEngineProvider


@dataclass(frozen=True)
class _ModelInfo:
    name: str
    engine: str
    kind: str
    shared: bool
    languages: tuple[str, ...]
    installed: bool
    path: str
    size_bytes: int


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0


class _Models:
    """Lists, downloads, redownloads, clears and cleans the models of every OCR engine.

    `languages` is a function giving the usable language specs; `profiles` the model profiles OCR
    phases ask for."""

    def __init__(
        self,
        providers: Callable[[], list[OcrEngineProvider]],
        languages: Callable[[], list[LanguageSpec]],
        profiles: Callable[[], list[str]],
        models_dir: Callable[[], Path],
        forget: Callable[[], None],
    ) -> None:
        self.providers = providers
        self.all_languages = languages
        self.profiles = profiles
        self.models_dir = models_dir
        self.forget = forget

    # ----- what there is ----------------------------------------------------------------------

    def _chosen(self, languages: Sequence[str] | None) -> list[LanguageSpec]:
        specs = self.all_languages()
        if languages is None:
            return specs
        if isinstance(languages, str):
            raise TypeError('languages must be a list of language ids, e.g. ["en"]')
        wanted = [str(c).strip().lower() for c in languages]
        known = {s.id: s for s in specs}
        unknown = [c for c in wanted if c not in known]
        if unknown:
            raise _InvalidSettingValueError(
                f"Unknown language {', '.join(repr(c) for c in unknown)}.",
                f"Available languages: {', '.join(known)}.",
            )
        return [known[c] for c in dict.fromkeys(wanted)]

    def _needed(self, provider: OcrEngineProvider, specs: list[LanguageSpec]) -> dict[str, dict]:
        """For each model the engine needs for these languages and the phases' profiles: its spec
        and the languages that use it."""
        found: dict[str, dict] = {}
        for spec in specs:
            for profile in self.profiles():
                if profile not in provider.profiles:
                    continue
                try:
                    models = provider.required_models(spec, profile)
                except Exception:  # noqa: BLE001 - this engine can't read that language
                    models = []
                for model in models:
                    entry = found.setdefault(model.name, {"model": model, "languages": []})
                    entry["languages"].append(spec.id)
        return found

    def list(self, languages: Sequence[str] | None = None) -> list[_ModelInfo]:
        models_dir = self.models_dir()
        infos: list[_ModelInfo] = []
        for provider in self.providers():
            for name, entry in self._needed(provider, self._chosen(languages)).items():
                path = provider.model_path(models_dir, name)
                model = entry["model"]
                infos.append(
                    _ModelInfo(
                        name=name,
                        engine=provider.id,
                        kind=model.kind,
                        shared=model.shared,
                        languages=tuple(entry["languages"]),
                        installed=path.exists(),
                        path=str(path),
                        size_bytes=_size(path),
                    )
                )
        return sorted(infos, key=lambda i: (i.engine, not i.shared, i.name))

    # ----- changing them ----------------------------------------------------------------------

    def _fetch(
        self,
        wanted: set[str] | None,
        languages: Sequence[str] | None,
        on_progress: ModelProgress | None,
    ) -> list[str]:
        """Download the missing models among `wanted` (all, if None). Returns the failures."""
        models_dir = self.models_dir()
        failures: list[str] = []
        for provider in self.providers():
            names = [
                name
                for name in self._needed(provider, self._chosen(languages))
                if (wanted is None or name in wanted)
                and not provider.model_path(models_dir, name).exists()
            ]
            if names:
                failed = provider.download(models_dir, names, on_progress)
                failures += [f"{name}: {why}" for name, why in failed.items()]
        self.forget()
        return failures

    def download(
        self, languages: Sequence[str] | None = None, on_progress: ModelProgress | None = None
    ) -> list[str]:
        return self._fetch(None, languages, on_progress)

    def redownload(
        self,
        names: Sequence[str] | None = None,
        languages: Sequence[str] | None = None,
        on_progress: ModelProgress | None = None,
    ) -> list[str]:
        wanted = None if names is None else set(names)
        models_dir = self.models_dir()
        for provider in self.providers():
            for name in self._needed(provider, self._chosen(languages)):
                if wanted is None or name in wanted:
                    self._remove(provider.model_path(models_dir, name))
        return self._fetch(wanted, languages, on_progress)

    @staticmethod
    def _remove(path: Path) -> bool:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return True
        if path.is_file():
            path.unlink(missing_ok=True)
            return True
        return False

    def clear(self, languages: Sequence[str], include_shared: bool = False) -> list[str]:
        """Delete the models only these languages use (and the shared ones too, with
        `include_shared`). Returns the names deleted."""
        chosen = self._chosen(languages)
        chosen_ids = {s.id for s in chosen}
        others = [s for s in self.all_languages() if s.id not in chosen_ids]
        models_dir = self.models_dir()
        removed: list[str] = []
        for provider in self.providers():
            kept = self._needed(provider, others)
            for name, entry in self._needed(provider, chosen).items():
                if entry["model"].shared and not include_shared:
                    continue
                if name in kept and not include_shared:
                    continue  # another language still reads with it
                if self._remove(provider.model_path(models_dir, name)):
                    removed.append(name)
        self.forget()
        return removed

    def clean(self) -> list[str]:
        """Delete the models no installed language needs any more. Returns the names deleted."""
        models_dir = self.models_dir()
        removed: list[str] = []
        for provider in self.providers():
            keep = {m.name for m in provider.known_models(self.all_languages())}
            parent = provider.model_path(models_dir, "x").parent
            if not parent.is_dir():
                continue
            for child in sorted(parent.iterdir()):
                if child.name not in keep and self._remove(child):
                    removed.append(child.name)
        self.forget()
        return removed
