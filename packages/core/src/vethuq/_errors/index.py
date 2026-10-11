"""Internal implementations of the indexing errors exposed in `vethuq.errors`."""

from __future__ import annotations

from vethuq import errors
from vethuq._errors.generic import _VethuQError


class _IndexingError(_VethuQError, errors.IndexingError):
    exit_code = 50


class _IndexAlreadyRunningError(_IndexingError, errors.IndexAlreadyRunningError):
    exit_code = 51


class _IndexRunNotFoundError(_IndexingError, errors.IndexRunNotFoundError):
    exit_code = 52


class _CreditsError(_VethuQError, errors.CreditsError):
    exit_code = 60


class _InvalidGrantError(_CreditsError, errors.InvalidGrantError):
    exit_code = 61


class _CreditsExhaustedError(_CreditsError, errors.CreditsExhaustedError):
    exit_code = 62


class _TierError(_VethuQError, errors.TierError):
    exit_code = 80


class _TierUnavailableError(_TierError, errors.TierUnavailableError):
    exit_code = 81


class _SearchError(_VethuQError, errors.SearchError):
    exit_code = 90


class _SearchUnavailableError(_SearchError, errors.SearchUnavailableError):
    exit_code = 91


class _SearchOptionError(_SearchError, errors.SearchOptionError):
    exit_code = 92

    def __init__(self, message: str, hint: str | None = None, option: str = "") -> None:
        super().__init__(message, hint)
        self.option = option


class _SearchQueryError(_SearchError, errors.SearchQueryError):
    exit_code = 93
