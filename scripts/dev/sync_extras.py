"""Keep `installer/shared/default-addons.txt` in step with the add-ons VethuQ depends on.

    python scripts/dev/sync_extras.py          # regenerate
    python scripts/dev/sync_extras.py --check  # exit 1 on drift (CI)

The list is every `vethuq-addon-*` dependency of packages/core (except the add-on API), one id
per line. The PyInstaller spec bakes these in; add-on and bundle installers skip them.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class SyncExtras:
    """Derives the default add-on list from the core package and writes or checks the file."""

    PYPROJECT = REPO_ROOT / "packages" / "core" / "pyproject.toml"
    TARGET = REPO_ROOT / "installer" / "shared" / "default-addons.txt"
    PREFIX = "vethuq-addon-"
    SKIP = frozenset({"api"})
    HEADER = (
        "# The add-ons VethuQ installs by default "
        "(the `vethuq-addon-*` dependencies of packages/core).\n"
        "# One id per line. The PyInstaller spec bakes these in; "
        "add-on and bundle installers skip them.\n"
    )

    def __init__(self, pyproject: Path = PYPROJECT, target: Path = TARGET) -> None:
        self.pyproject = pyproject
        self.target = target

    def ids(self) -> list[str]:
        """The default add-on ids, in the order core lists them."""
        data = tomllib.loads(self.pyproject.read_text(encoding="utf-8"))
        found: list[str] = []
        for requirement in data["project"]["dependencies"]:
            name = re.split(r"[\s<>=~!;\[]", requirement, maxsplit=1)[0].lower()
            if name.startswith(self.PREFIX) and name[len(self.PREFIX) :] not in self.SKIP:
                found.append(name[len(self.PREFIX) :])
        return found

    def render(self) -> str:
        return self.HEADER + "".join(f"{name}\n" for name in self.ids())

    def current(self) -> str:
        return self.target.read_text(encoding="utf-8") if self.target.exists() else ""

    def in_step(self) -> bool:
        return self.current() == self.render()

    def write(self) -> bool:
        """Regenerate the file; True if it changed."""
        if self.in_step():
            return False
        self.target.write_text(self.render(), encoding="utf-8", newline="\n")
        return True

    def main(self, argv: list[str]) -> int:
        if "--check" in argv:
            if self.in_step():
                return 0
            name = self.target.relative_to(REPO_ROOT)
            print(f"{name} is out of date: run scripts/dev/sync_extras.py")
            return 1
        changed = self.write()
        state = "Updated" if changed else "Already up to date:"
        print(f"{state} {self.target.relative_to(REPO_ROOT)}")
        return 0


if __name__ == "__main__":
    raise SystemExit(SyncExtras().main(sys.argv[1:]))
