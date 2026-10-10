"""Errors raised when reading and changing settings."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class SettingsError(VethuQError):
    """Base class for settings errors."""


class InvalidSettingValueError(SettingsError):
    """A value was given that the setting doesn't accept."""
