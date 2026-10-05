"""Vendor `vethuq-core` + `vethuq-cli` source into `packages/vethuq/src/vethuq`.

`vethuq` is the only distribution published to PyPI. `vethuq-core` and
`vethuq-cli` stay workspace-internal, so their code is copied in here
(under `vethuq._core` / `vethuq._cli`) with imports rewritten, rather than
declared as regular dependencies. Run this before building the `vethuq`
package, locally or in CI — the generated `_core`/`_cli` directories are
not committed.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VETHUQ_SRC = REPO_ROOT / "packages" / "vethuq" / "src" / "vethuq"

# (source package dir, source import name, vendored dir/subpackage name, names left out)
#
# The background service (core's `background` package and the CLI's `background.py`) ships with
# the desktop build only. It is not part of the `vethuq` package: its index functions always
# start a one-off worker. `Indexing.has_service()` notices the missing package at run time.
MERGES = [
    (
        REPO_ROOT / "packages" / "vethuq-core" / "src" / "vethuq_core",
        "vethuq_core",
        "_core",
        ("background",),
    ),
    (
        REPO_ROOT / "packages" / "vethuq-cli" / "src" / "vethuq_cli",
        "vethuq_cli",
        "_cli",
        ("background.py",),
    ),
]


def _rewrite_imports(text: str) -> str:
    for _, import_name, vendored_name, _excluded in MERGES:
        text = re.sub(rf"\b{import_name}\b", f"vethuq.{vendored_name}", text)
    return text


def merge() -> None:
    for source_dir, import_name, vendored_name, excluded in MERGES:
        if not source_dir.is_dir():
            raise FileNotFoundError(f"expected source package at {source_dir}")

        dest_dir = VETHUQ_SRC / vendored_name
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(
            source_dir,
            dest_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", *excluded),
        )

        py_files = list(dest_dir.rglob("*.py"))
        for py_file in py_files:
            rewritten = _rewrite_imports(py_file.read_text(encoding="utf-8"))
            py_file.write_text(rewritten, encoding="utf-8")

        print(f"vendored {import_name} -> vethuq.{vendored_name} ({len(py_files)} files)")


if __name__ == "__main__":
    merge()
