"""Fetch the signed policy over HTTPS with a short timeout, a size cap and conditional requests."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class FetchResponse:
    """A 200 with a body, or a 304 (`not_modified`) for the ETag that was sent."""

    url: str
    body: bytes | None
    etag: str | None
    not_modified: bool = False


@dataclass(frozen=True)
class FetchFailure:
    url: str
    reason: str


class PolicyFetcher:
    TIMEOUT_SECONDS = 2.5
    TOTAL_SECONDS = 5.0
    MAX_BYTES = 256 * 1024
    CHUNK_BYTES = 16 * 1024
    USER_AGENT = "VethuQ-policy/1"

    def __init__(
        self,
        urls: Sequence[str],
        *,
        timeout: float = TIMEOUT_SECONDS,
        total_timeout: float = TOTAL_SECONDS,
        max_bytes: int = MAX_BYTES,
        schemes: tuple[str, ...] = ("https",),
    ) -> None:
        self.urls = tuple(urls)
        self._timeout = timeout
        self._total_timeout = total_timeout
        self._max_bytes = max_bytes
        self._schemes = schemes

    def attempts(
        self, etag_url: str | None = None, etag: str | None = None
    ) -> Iterator[FetchResponse | FetchFailure]:
        """Try each URL in order, lazily, so the caller can stop at the first one it accepts.

        The ETag is only sent to the URL it came from. Nothing here raises.
        """
        for url in self.urls:
            try:
                yield self._get(url, etag if url == etag_url else None)
            except urllib.error.HTTPError as exc:
                if exc.code == 304:
                    yield FetchResponse(url, None, etag, not_modified=True)
                else:
                    yield FetchFailure(url, f"HTTP {exc.code}")
            except (OSError, ValueError) as exc:  # URLError, timeouts, resets, bad URLs
                yield FetchFailure(url, str(exc) or type(exc).__name__)

    def _get(self, url: str, etag: str | None) -> FetchResponse:
        if urlparse(url).scheme not in self._schemes:
            raise ValueError(f"scheme not allowed for {url}")
        headers = {"User-Agent": self.USER_AGENT, "Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 (scheme checked)
        deadline = time.monotonic() + self._total_timeout
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            if urlparse(response.geturl()).scheme not in self._schemes:
                raise ValueError("redirected to a disallowed scheme")
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}")
            declared = response.headers.get("Content-Length")
            if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
                raise ValueError("response too large")
            body = bytearray()
            while chunk := response.read(self.CHUNK_BYTES):
                body += chunk
                if len(body) > self._max_bytes:
                    raise ValueError("response too large")
                if time.monotonic() > deadline:
                    raise TimeoutError("response too slow")
            return FetchResponse(url, bytes(body), response.headers.get("ETag"))
