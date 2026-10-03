"""A file type VethuQ can read: its `type.json` manifest and whether it is usable here."""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vethuq_core.readers.reader import DocumentReader


@dataclass(frozen=True)
class FileType:
    """One `filetypes/<id>/type.json` manifest.

    `requires` are the pip requirements of the `type-<id>` extra; `modules` are the import
    names that prove they are present, which is how a type counts as installed - there is
    no separate state that could go stale.
    """

    id: str
    label: str
    extensions: tuple[str, ...]
    extra: str
    requires: tuple[str, ...]
    modules: tuple[str, ...]
    approx_size_mb: int
    default: bool
    reader: str

    @staticmethod
    def from_manifest(data: dict[str, Any]) -> FileType:
        return FileType(
            id=data["id"],
            label=data["label"],
            extensions=tuple(ext.lower() for ext in data["extensions"]),
            extra=data["extra"],
            requires=tuple(data.get("requires", ())),
            modules=tuple(data.get("modules", ())),
            approx_size_mb=int(data.get("approx_size_mb", 0)),
            default=bool(data.get("default", False)),
            reader=data["reader"],
        )

    def to_manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "extensions": list(self.extensions),
            "extra": self.extra,
            "requires": list(self.requires),
            "modules": list(self.modules),
            "approx_size_mb": self.approx_size_mb,
            "default": self.default,
            "reader": self.reader,
        }

    @property
    def install_hint(self) -> str:
        return f"pip install vethuq[{self.extra}]"

    def is_installed(self) -> bool:
        """Whether every module this type needs can be imported."""
        try:
            return all(importlib.util.find_spec(name) is not None for name in self.modules)
        except (ImportError, ValueError):
            return False

    def load_reader(self) -> DocumentReader:
        module_name, _, class_name = self.reader.partition(":")
        return getattr(importlib.import_module(module_name), class_name)()
