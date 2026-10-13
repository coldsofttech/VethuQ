"""Errors raised when reading and changing settings."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class SettingsError(VethuQError):
    """Base class for settings errors."""

    exit_code = 30


class InvalidSettingValueError(SettingsError):
    """A value was given that the setting doesn't accept."""

    exit_code = 31
