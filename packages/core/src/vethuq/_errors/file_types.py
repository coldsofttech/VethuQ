"""Internal name for the file type error in `vethuq.errors.file_types`.

It is an alias of the public class, so what is raised (and shown in a traceback) is the public
error.
"""

from __future__ import annotations

from vethuq import errors

_FileTypeUnavailableError = errors.FileTypeUnavailableError
