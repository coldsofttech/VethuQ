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


def bake(models: Path, say: Callable[[str], None] = print) -> int:
    """Download and check the models into `models`. Returns how many engines were verified."""
    from vethuq import VethuQ

    models.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vethuq-bake-") as folder:
        root = Path(folder)
        (root / "db").mkdir()
        (root / "models").symlink_to(models, target_is_directory=True)
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
                    needed = list(provider.required_models(language, phase.profile))
                    missing = [
                        m.name for m in needed if not provider.model_path(models, m.name).exists()
                    ]
                    if missing:
                        say(f"{language.id}/{phase.id}: downloading {', '.join(missing)}")
                        failed = provider.download(models, missing)
                        if failed:
                            raise BakeError(
                                f"Models failed to download: {', '.join(sorted(failed))}."
                            )
                    provider.create(language, phase.profile, models)
                    say(f"{language.id}/{phase.id}: ready")
                    checked += 1
            return checked
