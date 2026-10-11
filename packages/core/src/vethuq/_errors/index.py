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
