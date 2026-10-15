"""How this VethuQ was installed, and the exact steps that upgrade it.

VethuQ never upgrades itself in the running process (file locks on Windows, virtual environments,
PEP 668 externally-managed environments), so for a pip-style install this only says what to run.
"""

from __future__ import annotations

import sys
import sysconfig
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class InstallKind(StrEnum):
    """How VethuQ is installed."""

    INSTALLER = "installer"  # the desktop installer (a frozen build)
    PIPX = "pipx"
    VENV = "venv"  # pip inside a virtual environment
    EXTERNALLY_MANAGED = "externally-managed"  # a system Python that refuses pip (PEP 668)
    PIP = "pip"  # pip into a Python that allows it


@dataclass(frozen=True)
class UpgradeHelp:
    """The install type and the commands (or steps) that upgrade it. Nothing is run."""

    kind: InstallKind
    steps: tuple[str, ...]
    commands: tuple[str, ...] = ()  # the shell commands among the steps, ready to copy
    addons: tuple[str, ...] = ()  # add-on packages the steps include

    def to_dict(self) -> dict[str, object]:
        return {
            "install_type": self.kind.value,
            "steps": list(self.steps),
            "commands": list(self.commands),
            "addons": list(self.addons),
        }


class _Install:
    PACKAGE = "vethuq"

    @staticmethod
    def kind(
        *,
        frozen: bool | None = None,
        prefix: str | None = None,
        base_prefix: str | None = None,
        stdlib: str | None = None,
    ) -> InstallKind:
        """The install type; the arguments exist so tests can describe an environment."""
        if getattr(sys, "frozen", False) if frozen is None else frozen:
            return InstallKind.INSTALLER
        prefix = sys.prefix if prefix is None else prefix
        base_prefix = sys.base_prefix if base_prefix is None else base_prefix
        if prefix != base_prefix:
            parts = {part.lower() for part in Path(prefix).parts}
            return InstallKind.PIPX if "pipx" in parts else InstallKind.VENV
        stdlib = stdlib if stdlib is not None else sysconfig.get_path("stdlib")
        if stdlib and (Path(stdlib) / "EXTERNALLY-MANAGED").exists():
            return InstallKind.EXTERNALLY_MANAGED
        return InstallKind.PIP

    @staticmethod
    def help(kind: InstallKind, addons: Sequence[str] = ()) -> UpgradeHelp:
        names = tuple(dict.fromkeys(addons))
        if kind is InstallKind.INSTALLER:
            return UpgradeHelp(
                kind,
                (
                    "Open VethuQ and choose Install now in the update dialog, or download the "
                    "newest installer from the release notes page and run it.",
                    "Add-ons come with the installer and need no separate step.",
                ),
            )
        if kind is InstallKind.PIPX:
            commands = ["pipx upgrade vethuq"]
            if names:
                commands.append("pipx inject --force vethuq " + " ".join(names))
            return UpgradeHelp(kind, _Install._steps(commands), tuple(commands), names)
        everything = " ".join([_Install.PACKAGE, *names])
        if kind is InstallKind.EXTERNALLY_MANAGED:
            commands = [
                "python3 -m venv ~/.venvs/vethuq",
                f"~/.venvs/vethuq/bin/pip install --upgrade {everything}",
            ]
            steps = (
                "This Python is managed by your system, so pip will not change it (PEP 668). "
                "Use a virtual environment:",
                *_Install._steps(commands),
                "Or, with pipx: pipx upgrade vethuq",
            )
            return UpgradeHelp(kind, steps, tuple(commands), names)
        python = Path(sys.executable).name or "python"
        commands = [f"{python} -m pip install --upgrade {everything}"]
        return UpgradeHelp(kind, _Install._steps(commands), tuple(commands), names)

    @staticmethod
    def _steps(commands: Sequence[str]) -> tuple[str, ...]:
        return (*(f"Run: {command}" for command in commands), "Then start VethuQ again.")
