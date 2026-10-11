"""Fetching the OCR models while the worker image is built, so jobs never need the network.

For every language the installed add-ons provide and every OCR phase, the engine's models are
downloaded into one folder, and each engine is created once to prove the models load. Needs the
`run` extra.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path


class BakeError(Exception):
    """Models are missing or don't load."""


class Baker:
    """Downloads and checks the models into one folder.

    count = Baker(models).run()      # how many engines were verified
    """

    def __init__(self, models: Path, say: Callable[[str], None] = print) -> None:
        self._models = models
        self._say = say

    def run(self) -> int:
        from vethuq import VethuQ

        self._models.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="vethuq-bake-") as folder:
            root = Path(folder)
            (root / "db").mkdir()
            (root / "models").symlink_to(self._models, target_is_directory=True)
            with VethuQ(root / "db" / "vethuq.db") as client:
                manager = client._manager()
                languages = [spec for spec in manager.language_specs() if spec.available]
                phases = [spec for spec in manager.ocr_phase_specs() if spec.available]
                providers = [p for p in manager.ocr_engine_providers() if p.available]
                if not languages or not phases or not providers:
                    raise BakeError("No language, OCR phase or engine is installed.")
                checked = 0
                for phase in phases:
                    provider = next((p for p in providers if phase.profile in p.profiles), None)
                    if provider is None:
                        raise BakeError(f"No engine has the {phase.profile!r} models.")
                    for language in languages:
                        self._bake(provider, language, phase)
                        checked += 1
                return checked

    def _bake(self, provider, language, phase) -> None:
        needed = list(provider.required_models(language, phase.profile))
        missing = [m.name for m in needed if not provider.model_path(self._models, m.name).exists()]
        if missing:
            self._say(f"{language.id}/{phase.id}: downloading {', '.join(missing)}")
            failed = provider.download(self._models, missing)
            if failed:
                raise BakeError(f"Models failed to download: {', '.join(sorted(failed))}.")
        provider.create(language, phase.profile, self._models)
        self._say(f"{language.id}/{phase.id}: ready")
