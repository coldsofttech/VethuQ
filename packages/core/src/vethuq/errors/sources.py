"""Errors raised when registering and managing sources."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class SourceError(VethuQError):
    """Base class for source-registration errors."""

    exit_code = 20


class SourcePathError(SourceError):
    """The given path does not exist or is not a file or folder VethuQ can index."""

    exit_code = 21


class SourceAlreadyExistsError(SourceError):
    """The given path is already registered as a source."""

    exit_code = 22


class SourceNotFoundError(SourceError):
    """No registered source matches the given id or path."""

    exit_code = 23


class SourceOverlapError(SourceError):
    """The path lies inside an existing source, or contains one."""

    exit_code = 25


class SourceNotRemovedError(SourceError):
    """The source is still active, so it can't be purged."""

    exit_code = 24
