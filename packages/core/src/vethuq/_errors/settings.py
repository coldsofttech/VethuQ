"""Internal implementations of the settings errors exposed in `vethuq.errors`."""

from __future__ import annotations

from vethuq import errors
from vethuq._errors.generic import _VethuQError


class _SettingsError(_VethuQError, errors.SettingsError):
    exit_code = 30


class _InvalidSettingValueError(_SettingsError, errors.InvalidSettingValueError):
    exit_code = 31
