"""The notice printed after a command: a newer VethuQ, and the policy's active notices.

It only tells; it never asks. It is printed to stderr, and only when both stdout and stderr are a
terminal (so piped output and scripts are never touched), the command succeeded, the update check
is not switched off, and the command did not already report the same thing.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any, TextIO

from vethuq.enums import UpdateStatus
from vethuq_cli.console import Theme, error_console

# Commands that already show this information or are about it.
QUIET_COMMANDS = frozenset({"update", "updates", "policy"})
SEVERITY_STYLE = {"info": Theme.DIM, "warning": Theme.WARN, "critical": Theme.ERROR}


class AfterCommand:
    @staticmethod
    def wanted(
        argv: Sequence[str], *, stdout: TextIO | None = None, stderr: TextIO | None = None
    ) -> bool:
        """Whether a notice may be printed after this command line."""
        out, err = stdout or sys.stdout, stderr or sys.stderr
        if not (_tty(out) and _tty(err)):
            return False
        words = [a for a in argv if not a.startswith("-")]
        if not words or words[0] in QUIET_COMMANDS:
            return False
        return not any(a in ("--json", "--help", "--version", "-h") for a in argv)

    @staticmethod
    def lines(client: Any) -> list[tuple[str, str]]:
        """`(text, style)` lines to print; empty when there is nothing to say. Makes no request
        (it reads the saved policy) and never raises."""
        lines: list[tuple[str, str]] = []
        try:
            result = client.updates.status()
            if result.status is not UpdateStatus.DISABLED and result.notify and result.message:
                lines.append((f"{result.message} Run: vethuq update", Theme.WARN))
            if result.status is not UpdateStatus.DISABLED:
                for notice in client.policy.notices():
                    text = notice.message + (f" ({notice.link})" if notice.link else "")
                    prefix = "" if notice.severity == "info" else f"{notice.severity.upper()}: "
                    lines.append(
                        (f"{prefix}{text}", SEVERITY_STYLE.get(notice.severity, Theme.DIM))
                    )
        except Exception:  # noqa: BLE001 - a notice must never get in the way of the command
            return []
        return lines

    @staticmethod
    def print(client: Any, argv: Sequence[str]) -> None:
        if not AfterCommand.wanted(argv):
            return
        try:
            for text, style in AfterCommand.lines(client):
                error_console.print(text, style=style)
            # Look again in the background (at most about once a day) for the next command.
            client.policy.refresh_in_background()
        except Exception:  # noqa: BLE001
            return


def _tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False
