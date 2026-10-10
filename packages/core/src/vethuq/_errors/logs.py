"""Internal implementations of the log errors exposed in `vethuq.errors`."""

from __future__ import annotations

from vethuq import errors
from vethuq._errors.generic import _VethuQError


class _LogError(_VethuQError, errors.LogError):
    exit_code = 40


class _LogNotFoundError(_LogError, errors.LogNotFoundError):
    exit_code = 41


class _InvalidLogRequestError(_LogError, errors.InvalidLogRequestError):
    exit_code = 42
