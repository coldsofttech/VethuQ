"""Errors about the processing tiers: where the pages that need OCR are read."""

from __future__ import annotations

from vethuq.errors.generic import VethuQError


class TierError(VethuQError):
    """Base class for processing tier errors."""

    exit_code = 80


class TierUnavailableError(TierError):
    """The processing tier asked for can't be used now (not installed or not ready)."""

    exit_code = 81


class TierNotFoundError(TierUnavailableError):
    """No processing tier has the id asked for. The hint lists the tiers VethuQ knows."""

    exit_code = 82
