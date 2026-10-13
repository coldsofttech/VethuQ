"""Internal names for the language errors in `vethuq.errors.language`.

They are aliases of the public classes, so what is raised (and shown in a traceback) is the
public error.
"""

from __future__ import annotations

from vethuq import errors

_LastLanguageError = errors.LastLanguageError
_LanguageUnavailableError = errors.LanguageUnavailableError