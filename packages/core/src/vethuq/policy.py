"""The signed policy: `VethuQ().policy`.

The policy tells this VethuQ the latest and minimum versions, notices and feature flags without a
reinstall. It is fetched from a static file, checked against the Ed25519 keys built into VethuQ,
and cached; until one is accepted, a built-in baseline applies.

    result = client.policy.current()    # the cached policy or the baseline; no network
    result = client.policy.refresh()    # check for a newer one (about once a day)
    result.policy.active_notices()
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from vethuq._db import _Database
from vethuq._logs import _PolicyLog
from vethuq._paths import _Paths
from vethuq._policy import (
    AddonPolicy,
    DistributionVersions,
    Feature,
    Notice,
    Policy,
    PolicyResult,
    _PolicyClient,
)
from vethuq.enums import PolicySource, PolicyStatus

__all__ = [
    "AddonPolicy",
    "DistributionVersions",
    "Feature",
    "Notice",
    "Policy",
    "PolicyClient",
    "PolicyResult",
    "PolicySource",
    "PolicyStatus",
]


class PolicyClient:
    """Reads and refreshes the signed policy.

    Not created directly: use `VethuQ().policy`. Nothing is fetched on import, when the client is
    created or when this object is first used; only `refresh()` and `refresh_in_background()` use
    the network, and none of the methods raises: a problem keeps the last good policy (or the
    baseline), so offline use and local work are never blocked.
    """

    def __init__(self, database: _Database) -> None:
        self._database = database
        self._client: _PolicyClient | None = None
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        """The folder holding the cached policy and its state."""
        return _Paths.policy_dir(self._database.db_path, create=False)

    def _policy_client(self) -> _PolicyClient:
        with self._lock:
            if self._client is None:
                logger: logging.Logger = _PolicyLog.setup(self._database.db_path)
                self._client = _PolicyClient(self.directory, logger=logger)
            return self._client

    def current(self) -> PolicyResult:
        """The policy to use now: the cached one, else the baseline. Makes no request."""
        return self._policy_client().current()

    def refresh(self, force: bool = False) -> PolicyResult:
        """Check for a newer policy and return the one to use.

        It asks at most about once a day (after a failed check, once an hour) unless `force` is
        true. While no policy keys are built into VethuQ it makes no request and returns
        `PolicyStatus.SKIPPED`.
        """
        return self._policy_client().refresh(force=force)

    def refresh_in_background(self, force: bool = False) -> threading.Thread:
        """Run `refresh` on a daemon thread, so starting up is never delayed."""
        return self._policy_client().refresh_in_background(force=force)
