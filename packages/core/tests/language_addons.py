"""Builds installed language add-ons (a module and a `.dist-info` with an entry point) for tests."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

SOURCE = """
from vethuq_addon_api import Addon, LanguageSpec, Manifest

SPECS = {specs}


class {cls}(Addon):
    manifest = Manifest(id="{addon_id}", name="vethuq-addon-{addon_id}", version="0.1.0")

    def languages(self):
        return [LanguageSpec(**spec) for spec in SPECS]
"""

ENGLISH = {"id": "en", "label": "English", "script": "latin", "default": True}
TELUGU = {"id": "te", "label": "Telugu", "native_label": "తెలుగు", "script": "telugu"}


class LanguageAddonFactory:
    @staticmethod
    def install(folder: Path, addon_id: str, specs: list[dict], cls: str | None = None) -> str:
        """Create the language add-on in `folder` and put `folder` on `sys.path`."""
        module = f"vethuq_addon_{addon_id}"
        cls = cls or f"{addon_id.title()}Addon"
        source = SOURCE.format(specs=repr(specs), cls=cls, addon_id=addon_id)
        (folder / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")
        dist = folder / f"{module}-0.1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {module}\nVersion: 0.1.0\n", encoding="utf-8"
        )
        (dist / "entry_points.txt").write_text(
            f"[vethuq.addons]\n{addon_id} = {module}:{cls}\n", encoding="utf-8"
        )
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
        return module

    @staticmethod
    def forget(module: str) -> None:
        for name in [n for n in sys.modules if n == module]:
            del sys.modules[name]
        sys.modules.pop("vethuq.addons." + module.removeprefix("vethuq_addon_"), None)
