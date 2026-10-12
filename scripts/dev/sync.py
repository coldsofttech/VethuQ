"""Restore the full workspace install (all packages + dev tools).

    uv run python scripts/dev/sync.py

A plain `uv sync` only syncs the current project, which can drop the other workspace members and
leave `vethuq` unrecognized. Run this after pulling changes that touch pyproject.toml or uv.lock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class Sync:
    """Runs `uv sync` for every workspace package and the dev group."""

    REPO_ROOT = Path(__file__).resolve().parents[2]
    COMMAND = ("uv", "sync", "--all-packages", "--group", "dev")

    def __init__(self, root: Path = REPO_ROOT) -> None:
        self.root = root

    def run(self) -> int:
        return subprocess.call(self.COMMAND, cwd=self.root)  # noqa: S603 - fixed command


if __name__ == "__main__":
    sys.exit(Sync().run())
