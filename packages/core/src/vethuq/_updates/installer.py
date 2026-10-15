"""Download the desktop installer named by the signed policy and check it before it is run.

The policy lists, per platform, the installer's `url`, `size` and `sha256` (see policy schema v1).
Because the policy itself is signature-checked, a matching hash makes the file as trustworthy as
the policy. Nothing is run here: a file that fails any check is deleted and never returned.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from vethuq._policy import Policy


class InstallerError(Exception):
    """The installer could not be fetched or did not match the policy."""


@dataclass(frozen=True)
class InstallerDownload:
    """One installer the policy offers for a platform."""

    platform: str
    url: str
    size: int
    sha256: str


class _Installer:
    CHUNK_BYTES = 1024 * 256
    TIMEOUT_SECONDS = 30.0

    @staticmethod
    def platform_key() -> str:
        """The policy's platform name for this machine (`windows-x64`, `linux-x64`, ...)."""
        import platform  # noqa: PLC0415 - only needed here

        machine = platform.machine().lower()
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
        return f"{system}-{arch}"

    @staticmethod
    def entry(
        policy: Policy, distribution: str = "desktop", platform: str | None = None
    ) -> InstallerDownload | None:
        """The download for `platform` (this machine by default), or None when the policy has none
        or the entry is malformed. Entries are never half-trusted: all four fields must be valid."""
        wanted = platform or _Installer.platform_key()
        versions: Any = policy.raw.get("versions")
        node = versions.get(distribution) if isinstance(versions, dict) else None
        downloads = node.get("downloads") if isinstance(node, dict) else None
        for item in downloads if isinstance(downloads, list) else []:
            if not isinstance(item, dict) or item.get("platform") != wanted:
                continue
            url, size, digest = item.get("url"), item.get("size"), item.get("sha256")
            valid = (
                isinstance(url, str)
                and urlparse(url).scheme == "https"
                and isinstance(size, int)
                and not isinstance(size, bool)
                and size > 0
                and isinstance(digest, str)
                and len(digest) == 64
                and all(c in "0123456789abcdef" for c in digest)
            )
            if valid:
                return InstallerDownload(wanted, url, size, digest)
        return None

    @staticmethod
    def fetch(
        entry: InstallerDownload,
        directory: Path,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        schemes: tuple[str, ...] = ("https",),
    ) -> Path:
        """Download `entry` into `directory` and return the file, only if its size and sha256 match
        the policy. Raises `InstallerError`; whatever was written is removed on any failure."""
        if urlparse(entry.url).scheme not in schemes:
            raise InstallerError("The installer address is not secure (https).")
        directory.mkdir(parents=True, exist_ok=True)
        name = Path(urlparse(entry.url).path).name or "vethuq-installer"
        target = directory / name
        partial = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        total = 0
        try:
            request = urllib.request.Request(  # noqa: S310 - scheme checked above
                entry.url, headers={"User-Agent": "VethuQ-updater/1"}
            )
            with opener(request, timeout=_Installer.TIMEOUT_SECONDS) as response:
                if urlparse(response.geturl()).scheme not in schemes:
                    raise InstallerError("The download was redirected to an insecure address.")
                with open(partial, "wb") as handle:
                    while chunk := response.read(_Installer.CHUNK_BYTES):
                        total += len(chunk)
                        if total > entry.size:
                            raise InstallerError("The installer is larger than the policy says.")
                        digest.update(chunk)
                        handle.write(chunk)
            if total != entry.size:
                raise InstallerError("The installer is smaller than the policy says.")
            if not hmac.compare_digest(digest.hexdigest(), entry.sha256):
                raise InstallerError("The installer does not match its checksum; it was not run.")
            partial.replace(target)
            return target
        except InstallerError:
            partial.unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as exc:
            partial.unlink(missing_ok=True)
            raise InstallerError(f"The installer could not be downloaded: {exc}") from exc
