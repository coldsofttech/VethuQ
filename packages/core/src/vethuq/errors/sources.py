"""Errors raised when registering and managing sources."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class SourceError(VethuQError):
    """Base class for source-registration errors."""


class SourcePathError(SourceError):
    """The given path does not exist or is not a file or folder VethuQ can index."""


class SourceAlreadyExistsError(SourceError):
    """The given path is already registered as a source."""
