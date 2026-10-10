"""Makes `vethuq.addons.<id>` an alias for the installed add-on package `vethuq_addon_<id>`."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from types import ModuleType
from typing import Any

PREFIX = "vethuq.addons."
REAL_PREFIX = "vethuq_addon_"


class _AliasLoader(importlib.abc.Loader):
    """Hands out the real module itself, so `vethuq.addons.backup` and `vethuq_addon_backup` are
    one module (one set of classes) and nothing is imported twice."""

    def __init__(self, module: ModuleType) -> None:
        self._module = module

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        return self._module

    def exec_module(self, module: ModuleType) -> None:
        return None


class _AddonFinder(importlib.abc.MetaPathFinder):
    """`from vethuq.addons.backup import Backup` imports `vethuq_addon_backup` if it is installed;
    otherwise it raises the usual `ModuleNotFoundError`."""

    @staticmethod
    def real_name(fullname: str) -> str | None:
        if not fullname.startswith(PREFIX):
            return None
        addon_id, _, rest = fullname[len(PREFIX) :].partition(".")
        if not addon_id.replace("_", "").replace("-", "").isalnum():
            return None
        real = REAL_PREFIX + addon_id.replace("-", "_")
        return f"{real}.{rest}" if rest else real

    def find_spec(
        self, fullname: str, path: Any = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        real_name = self.real_name(fullname)
        if real_name is None:
            return None
        try:
            real = importlib.import_module(real_name)
        except ModuleNotFoundError as exc:
            if exc.name is not None and real_name.startswith(exc.name):
                return None  # the add-on isn't installed
            raise
        return importlib.util.spec_from_loader(
            fullname, _AliasLoader(real), is_package=hasattr(real, "__path__")
        )

    @staticmethod
    def install() -> None:
        """Put the finder first on `sys.meta_path`, once."""
        if not any(isinstance(finder, _AddonFinder) for finder in sys.meta_path):
            sys.meta_path.insert(0, _AddonFinder())
