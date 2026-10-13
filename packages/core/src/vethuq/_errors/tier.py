"""Internal names for the tier errors in `vethuq.errors.tier`.

They are aliases of the public classes, so what is raised (and shown in a traceback) is the
public error.
"""

from __future__ import annotations

from vethuq import errors

_TierError = errors.TierError
_TierUnavailableError = errors.TierUnavailableError
_TierNotFoundError = errors.TierNotFoundError
