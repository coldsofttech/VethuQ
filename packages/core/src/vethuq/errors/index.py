"""Errors raised when indexing."""

from __future__ import annotations

from vethuq.errors.generic import CorruptDatabaseError, VethuQError


class IndexingError(VethuQError):
    """Base class for indexing errors."""


class IndexAlreadyRunningError(IndexingError):
    """An index run is already going."""


class IndexRunNotFoundError(IndexingError):
    """There is no index run with that id."""


class IndexNotRunningError(IndexingError):
    """There is no index run going to pause, resume or stop."""


class FileNotTrackedError(IndexingError):
    """The file is not one VethuQ tracks: it isn't under an active source, or hasn't been seen."""


class CreditsError(VethuQError):
    """Base class for credit errors."""


class InvalidGrantError(CreditsError):
    """A credit grant or licence can't be redeemed."""


class CreditsExhaustedError(CreditsError):
    """There aren't enough credits for the work."""


class TierError(VethuQError):
    """Base class for processing tier errors."""


class TierUnavailableError(TierError):
    """The processing tier asked for can't be used now (unknown, not installed, or not ready)."""


class SearchError(VethuQError):
    """Base class for search errors."""


class SearchUnavailableError(SearchError):
    """The search engine asked for isn't known or can't be used now."""


class SearchOptionError(SearchError):
    """A search option can't be honoured (an unknown normalizer or level, or one the engine
    can't change). `option` names which."""

    option: str = ""


class SearchQueryError(SearchError):
    """The query can't be searched by the engine."""


class DatabaseIntegrityError(IndexingError, CorruptDatabaseError):
    """The database failed its integrity check when a run started after an earlier run had been
    left behind by a process that ended. Nothing was changed; repair or restore the database."""
