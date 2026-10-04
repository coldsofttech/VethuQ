"""A file type VethuQ can read: its `type.json` manifest and whether it is usable here."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vethuq_core.readers.reader import DocumentReader


@dataclass(frozen=True)
class FileTypeInfo:
    """What `client.file_types.list()` returns for one file type."""

    id: str
    label: str
    extensions: tuple[str, ...]
    package: str
    installed: bool
    enabled: bool
    install_hint: str | None


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

    @property
    def marker(self) -> str | None:
        """The tiny distribution the `type-<id>` extra pulls in, so pip records the choice.

        The default type has none: its requirements are base dependencies.
        """
        return None if self.default else f"vethuq-{self.extra}"

    def marker_installed(self) -> bool:
        """Whether `pip install vethuq[type-<id>]` was run (the marker distribution is present)."""
        if self.marker is None:
            return False
        try:
            importlib.metadata.version(self.marker)
        except importlib.metadata.PackageNotFoundError:
            return False
        return True

    def is_installed(self) -> bool:
        """Whether every module this type needs can be imported.

        The desktop build bundles every type (the installer's selection decides which are
        enabled), but the UI and CLI exes can't import the libraries the worker carries, so
        a frozen build counts all types as installed.
        """
        if getattr(sys, "frozen", False):
            return True
        try:
            return all(importlib.util.find_spec(name) is not None for name in self.modules)
        except (ImportError, ValueError):
            return False

    def load_reader(self) -> DocumentReader:
        module_name, _, class_name = self.reader.partition(":")
        return getattr(importlib.import_module(module_name), class_name)()
