#!/usr/bin/env python3
"""Drop what a running worker never reads from an installed Python tree (the image build runs it).

    python slim.py /opt/venv

Removes byte-code and caches, the test suites and documentation folders that packages ship inside
their own package folder, and static-library and header files. It never touches `*.dist-info` (the
licences and the entry points live there) or any Python module a package imports, and running it
again changes nothing, so every layer of the image can run it over what it just installed.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Folders named like this inside a package are a test suite or documentation, not code it imports.
JUNK_DIRS = frozenset({"tests", "test", "doc", "docs", "examples", "example", "benchmarks"})
# Never looked inside: licences, entry points and the record of what is installed.
KEEP_SUFFIXES = (".dist-info", ".egg-info")
JUNK_FILES = frozenset({".a", ".la", ".h", ".hpp", ".pyc", ".pyo", ".c", ".cpp", ".pyx", ".pxd"})


class Slimmer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.removed = 0
        self.bytes = 0

    def run(self) -> int:
        """Slim every `site-packages` folder under the root. Returns how many things went."""
        for site in sorted(self.root.rglob("site-packages")):
            if site.is_dir():
                self._slim(site)
        return self.removed

    # ----- internals ---------------------------------------------------------------------------

    def _slim(self, site: Path) -> None:
        for path in sorted(site.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if not path.exists() and not path.is_symlink():
                continue  # inside something already removed
            if self._kept(path, site):
                continue
            if path.is_dir() and not path.is_symlink():
                if path.name == "__pycache__" or (
                    path.name in JUNK_DIRS and len(path.relative_to(site).parts) >= 2
                ):
                    self._remove(path)
            elif path.suffix in JUNK_FILES and not path.is_dir():
                self._remove(path)

    @staticmethod
    def _kept(path: Path, site: Path) -> bool:
        return any(part.endswith(KEEP_SUFFIXES) for part in path.relative_to(site).parts)

    def _remove(self, path: Path) -> None:
        try:
            self.bytes += self._size(path)
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
            self.removed += 1
        except OSError:
            pass  # something that can't be removed is just left

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size
        return sum(p.lstat().st_size for p in path.rglob("*") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    paths = [Path(a) for a in (sys.argv[1:] if argv is None else argv)]
    if not paths:
        print("usage: slim.py ROOT [ROOT...]", file=sys.stderr)
        return 2
    for root in paths:
        slimmer = Slimmer(root)
        count = slimmer.run()
        print(f"slim: removed {count} item(s), about {slimmer.bytes // 1024} KiB, from {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
