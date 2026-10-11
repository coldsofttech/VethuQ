"""The master key: a random 256-bit key that encrypts the pages sent to the runner. It is kept
in the data folder, readable only by you, and given to the runner repository as a secret."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import secrets
from pathlib import Path

from vethuq._errors import _GitHubSetupError


class _MasterKey:
    FILENAME = "master.key"
    SIZE = 32

    def __init__(self, folder: Path) -> None:
        self.path = Path(folder) / self.FILENAME

    @staticmethod
    def encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def decode(text: str) -> bytes:
        try:
            raw = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
        except (binascii.Error, ValueError):
            raw = b""
        if len(raw) != _MasterKey.SIZE:
            raise _GitHubSetupError(
                "The master key isn't a valid 256-bit key.",
                "Leave it out to have one generated.",
            )
        return raw

    def exists(self) -> bool:
        return self.path.is_file()

    def read(self) -> str:
        """The key as text (what the secret holds). Raises if there is none."""
        if not self.exists():
            raise _GitHubSetupError(
                "The master key is missing.", "Run setup again, passing master_key= to restore it."
            )
        text = self.path.read_text(encoding="ascii").strip()
        self.decode(text)
        return text

    def write(self, text: str) -> None:
        """Save a key, readable by this user only."""
        self.decode(text)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(text.strip() + "\n")
        try:
            self.path.chmod(0o600)
        except OSError:  # not every file system keeps permissions
            pass

    def obtain(self, given: str | bytes | None = None) -> str:
        """The key to use: the one given (and saved), else the one already kept, else a new one."""
        if given is not None:
            text = self.encode(given) if isinstance(given, bytes) else str(given).strip()
            self.write(text)
            return text
        if self.exists():
            return self.read()
        text = self.encode(secrets.token_bytes(self.SIZE))
        self.write(text)
        return text

    @staticmethod
    def fingerprint(text: str) -> str:
        """A short, harmless identifier of a key, to tell keys apart."""
        return hashlib.sha256(_MasterKey.decode(text)).hexdigest()[:8]

    def remove(self) -> bool:
        if self.exists():
            self.path.unlink()
            return True
        return False
