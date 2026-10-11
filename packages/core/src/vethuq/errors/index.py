"""Errors raised when indexing."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class IndexingError(VethuQError):
    """Base class for indexing errors."""


class IndexAlreadyRunningError(IndexingError):
    """An index run is already going."""


class IndexRunNotFoundError(IndexingError):
    """There is no index run with that id."""
