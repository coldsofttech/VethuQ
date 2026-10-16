"""Errors about licences: installing one and asking for one."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class LicenceError(VethuQError):
    """Base class for licence errors."""

    exit_code = 65


class InvalidLicenceError(LicenceError):
    """A licence can't be installed: it isn't readable, isn't valid, or lists nothing to unlock."""

    exit_code = 66


class LicenceRequestError(LicenceError):
    """A licence request can't be made (no `vethuq-entitlements`, no GitHub id, a bad field)."""

    exit_code = 67
