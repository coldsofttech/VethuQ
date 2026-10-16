"""Errors raised when indexing."""

from __future__ import annotations

from vethuq.errors.generic import CorruptDatabaseError, VethuQError


class IndexingError(VethuQError):
    """Base class for indexing errors."""

    exit_code = 50


class IndexAlreadyRunningError(IndexingError):
    """An index run is already going."""

    exit_code = 51


class IndexRunNotFoundError(IndexingError):
    """There is no index run with that id."""

    exit_code = 52


class IndexNotRunningError(IndexingError):
    """There is no index run going to pause, resume or stop."""

    exit_code = 53


class FileNotTrackedError(IndexingError):
    """The file is not one VethuQ tracks: it isn't under an active source, or hasn't been seen."""

    exit_code = 54


class CreditsError(VethuQError):
    """Base class for credit errors."""

    exit_code = 60


class InvalidGrantError(CreditsError):
    """A credit grant or licence can't be redeemed."""

    exit_code = 61


class CreditsExhaustedError(CreditsError):
    """There aren't enough credits for the work."""

    exit_code = 62


class SearchError(VethuQError):
    """Base class for search errors."""

    exit_code = 90


class SearchUnavailableError(SearchError):
    """The search engine asked for isn't known or can't be used now."""

    exit_code = 91


class SearchOptionError(SearchError):
    """A search option can't be honoured (an unknown normalizer or level, or one the engine
    can't change). `option` names which."""

    exit_code = 92

    option: str = ""

    def __init__(self, message: str, hint: str | None = None, option: str = "") -> None:
        super().__init__(message, hint)
        self.option = option


class SearchQueryError(SearchError):
    """The query can't be searched by the engine."""

    exit_code = 93


class DatabaseIntegrityError(IndexingError, CorruptDatabaseError):
    """The database failed its integrity check when a run started after an earlier run had been
    left behind by a process that ended. Nothing was changed; repair or restore the database."""

    exit_code = 55


class IndexJobNotFoundError(IndexingError):
    """There is no queued index request with that id."""

    exit_code = 56


class IndexJobStateError(IndexingError):
    """The request is not in a state that allows that (only a queued request can be cancelled)."""

    exit_code = 57
