"""Errors raised when reading logs."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class LogError(VethuQError):
    """Base class for log errors."""

    exit_code = 40


class LogNotFoundError(LogError):
    """There is no log for that component and day."""

    exit_code = 41


class InvalidLogRequestError(LogError):
    """A request to read logs had an argument that can't be used."""

    exit_code = 42
