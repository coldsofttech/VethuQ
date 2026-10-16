"""Internal names for the licence errors in `vethuq.errors.licence`.

They are aliases of the public classes, so what is raised (and shown in a traceback) is the
public error.
"""

from __future__ import annotations

from vethuq import errors

_LicenceError = errors.LicenceError
_InvalidLicenceError = errors.InvalidLicenceError
_LicenceRequestError = errors.LicenceRequestError
