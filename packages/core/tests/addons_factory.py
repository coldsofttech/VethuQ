"""Builds a tiny installed add-on (a module and a `.dist-info` with an entry point) in a folder."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

ADDON_SOURCE = '''
from vethuq_addon_api import Addon, Manifest

EVENTS = []


class Dummy:
    """The add-on's public class."""

    def __init__(self, client):
        self.client = client


class DummyAddon(Addon):
    manifest = Manifest(id="{addon_id}", name="vethuq-addon-{addon_id}", version="1.2.3"{api})

    def on_open(self):
        EVENTS.append(("open", self.host.get_setting("seen", "none")))
        self.host.set_setting("seen", "yes")
        {open_extra}

    def before_migration(self, info):
        EVENTS.append(("migrate", info.from_version, info.to_version))
'''


class AddonFactory:
    @staticmethod
    def install(
        folder: Path,
        addon_id: str = "dummy",
        *,
        entry_name: str | None = None,
        api: str = "",
        open_extra: str = "pass",
        target: str | None = None,
    ) -> str:
        """Create the add-on in `folder`, put `folder` on `sys.path`, return the module name."""
        module = f"vethuq_addon_{addon_id}"
        source = ADDON_SOURCE.format(addon_id=addon_id, api=api, open_extra=open_extra)
        (folder / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")
        dist = folder / f"{module}-1.2.3.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {module}\nVersion: 1.2.3\n", encoding="utf-8"
        )
        point = target or f"{module}:DummyAddon"
        (dist / "entry_points.txt").write_text(
            f"[vethuq.addons]\n{entry_name or addon_id} = {point}\n", encoding="utf-8"
        )
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
        return module

    @staticmethod
    def forget(module: str) -> None:
        for name in [n for n in sys.modules if n == module or n.startswith(module + ".")]:
            del sys.modules[name]
        for name in [n for n in sys.modules if n.startswith("vethuq.addons.") and n != "vethuq.addons.manage"]:
            del sys.modules[name]
