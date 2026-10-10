"""Internal implementations of the source errors exposed in `vethuq.errors`."""

from __future__ import annotations

from vethuq import errors
from vethuq._errors.generic import _VethuQError


class _SourceError(_VethuQError, errors.SourceError):
    exit_code = 20


class _SourcePathError(_SourceError, errors.SourcePathError):
    exit_code = 21


class _SourceAlreadyExistsError(_SourceError, errors.SourceAlreadyExistsError):
    exit_code = 22
