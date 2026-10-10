"""The one policy client a running program shares, and how the front ends start it."""

from __future__ import annotations

import logging
import threading

from vethuq_core.policy.client import PolicyClient, PolicyResult


class PolicyService:
    """Process-wide access to the policy for the CLI, the desktop app and the library.

    The CLI and the desktop app call `start()` once at startup; the pip package never does,
    so the library only fetches when its caller asks (`PolicyClient.refresh()`).
    """

    _client: PolicyClient | None = None
    _lock = threading.Lock()

    @staticmethod
    def client(logger: logging.Logger | None = None) -> PolicyClient:
        """The shared client, created on first use (no I/O, no network)."""
        with PolicyService._lock:
            if PolicyService._client is None:
                PolicyService._client = PolicyClient(logger=logger)
            return PolicyService._client

    @staticmethod
    def start(logger: logging.Logger | None = None) -> threading.Thread | None:
        """Refresh the policy on a daemon thread so startup is never delayed.

        Never raises. Returns the thread, or None if it could not be started.
        """
        try:
            return PolicyService.client(logger).refresh_in_background()
        except Exception:  # noqa: BLE001 - the policy must never stop VethuQ from starting
            (logger or logging.getLogger("vethuq.policy")).warning(
                "Could not start the policy refresh", exc_info=True
            )
            return None

    @staticmethod
    def current(logger: logging.Logger | None = None) -> PolicyResult:
        """The policy to use now (cached or baseline), without any network."""
        return PolicyService.client(logger).current()

    @staticmethod
    def reset() -> None:
        """Forget the shared client (for tests)."""
        with PolicyService._lock:
            PolicyService._client = None
