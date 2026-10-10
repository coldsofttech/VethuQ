"""Errors raised when registering and managing sources."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class SourceError(VethuQError):
    """Base class for source-registration errors."""


class SourcePathError(SourceError):
    """The given path does not exist or is not a file or folder VethuQ can index."""


class SourceAlreadyExistsError(SourceError):
    """The given path is already registered as a source."""


class SourceNotFoundError(SourceError):
    """No registered source matches the given id or path."""


class SourceOverlapError(SourceError):
    """The path lies inside an existing source, or contains one."""


class SourceNotRemovedError(SourceError):
    """The source is still active, so it can't be purged."""
