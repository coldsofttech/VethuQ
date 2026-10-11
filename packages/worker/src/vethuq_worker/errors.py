"""What can go wrong with a job."""

from __future__ import annotations


class JobError(Exception):
    """A job can't be read or built. `code` is stable: `bad_key`, `bad_payload`, `bad_manifest`,
    `unsupported_protocol`, `too_many_pages`, `too_large`, `bad_result`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
