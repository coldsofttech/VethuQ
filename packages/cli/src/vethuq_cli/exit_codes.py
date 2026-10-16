"""Exit codes that report a state rather than an error, for scripts. Errors keep their own codes
(`vethuq.errors`; see the table in the README). A command that can report one of these says so
with a flag (`--exit-code`), except a run that stopped for lack of credits, which always does."""

from __future__ import annotations

import typer

WAITING_CREDITS = 63  # an index run stopped: the credits ran out, run again after the reset
WAITING_REMOTE = 64  # an index run sent pages away: collect the results later
LICENCE_NOT_OK = 65  # an installed licence is expired, revoked or not for this device
CREDITS_EMPTY = 62  # nothing is left to spend (the same code as `CreditsExhaustedError`)
UPDATE_AVAILABLE = 100  # a newer version exists
BELOW_MINIMUM = 101  # this version is older than the minimum supported

ExitCode = typer.Option(
    False, "--exit-code", help="Exit with a code that tells the state (see the README)."
)


def leave(code: int) -> None:
    raise typer.Exit(code)
