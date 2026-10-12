"""Whether the VethuQ background service is installed, and in what state (Windows only)."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Protocol

SERVICE_NAME = "VethuQBackground"
_NOT_INSTALLED = 1060  # ERROR_SERVICE_DOES_NOT_EXIST
_NEVER_STARTED = 1077  # ERROR_SERVICE_NEVER_STARTED: stopped, but not through a failure


@dataclass(frozen=True)
class ServiceInfo:
    """What `sc query` says about the service."""

    state: str  # RUNNING, STOPPED, PAUSED, START_PENDING, STOP_PENDING, ...
    exit_code: int = 0  # why it last stopped; 0 for a clean stop


class ServiceProbe(Protocol):
    def query(self) -> ServiceInfo | None:
        """The service, or None when it is not installed (or this is not Windows)."""


def parse_query(output: str) -> ServiceInfo | None:
    """Read the text `sc query VethuQBackground` prints."""
    state = re.search(r"STATE\s*:\s*\d+\s+(\w+)", output)
    if state is None:
        return None
    exit_code = re.search(r"WIN32_EXIT_CODE\s*:\s*(\d+)", output)
    specific = re.search(r"SERVICE_EXIT_CODE\s*:\s*(\d+)", output)
    code = int(exit_code.group(1)) if exit_code else 0
    if code in (0, _NEVER_STARTED) and specific and int(specific.group(1)):
        code = int(specific.group(1))
    return ServiceInfo(state.group(1), 0 if code == _NEVER_STARTED else code)


class WindowsServiceProbe:
    """Asks the service manager with `sc query`, which needs no administrator rights. The answer is
    kept for a couple of seconds, so a status bar polling every second does not start a process
    every time."""

    def __init__(self, ttl: float = 2.0) -> None:
        self._ttl = ttl
        self._at = float("-inf")
        self._info: ServiceInfo | None = None

    def query(self) -> ServiceInfo | None:
        if sys.platform != "win32":
            return None
        now = time.monotonic()
        if now - self._at >= self._ttl:
            self._info = self._ask()
            self._at = now
        return self._info

    def forget(self) -> None:
        self._at = float("-inf")

    @staticmethod
    def _ask() -> ServiceInfo | None:
        try:
            done = subprocess.run(  # noqa: S603
                ["sc.exe", "query", SERVICE_NAME],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode == _NOT_INSTALLED:
            return None
        return parse_query(done.stdout)


def colour(info: ServiceInfo, *, working: bool, announced: bool) -> tuple[str, str, str]:
    """`(colour, label, tooltip)` for the status bar dot.

    Green: running and idle. Amber: a run is going, or the service is starting, stopping or
    paused. Red: it stopped because of an error. Grey: it stopped normally.
    """
    state = info.state
    if state == "STOPPED":
        if info.exit_code:
            why = f"The background service stopped with an error (code {info.exit_code})."
            return "red", "Error", why
        return "grey", "Stopped", "The background service is installed but not running."
    if state == "PAUSED":
        return "amber", "Paused", "The background service is paused."
    if state.endswith("_PENDING"):
        return "amber", "Starting", "The background service is changing state."
    if working:
        return "amber", "Processing", "The background service is indexing."
    if not announced:
        return "amber", "Starting", "The background service is starting."
    return "green", "Idle", "The background service is running and waiting for work."
