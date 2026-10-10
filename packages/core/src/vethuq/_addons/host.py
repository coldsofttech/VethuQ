"""The `Host` an add-on receives."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from vethuq_addon_api import API_VERSION

from vethuq._addons.settings import _AddonSettingsStore
from vethuq._logs import _DatabaseLog
from vethuq._db import _Schema
from vethuq._paths import _Paths
from vethuq._policy import Policy, _PolicyClient
from vethuq._version import _Version


class _Host:
    """One per add-on, so its settings and log lines are its own."""

    def __init__(
        self,
        addon_id: str,
        db_path: Path,
        release_database: Callable[[], None],
        policy: Callable[[], Policy | None] | None = None,
    ) -> None:
        self._policy_source = policy
        self._addon_id = addon_id
        self._db_path = Path(db_path)
        self._release = release_database
        self._settings = _AddonSettingsStore(self._db_path, addon_id)

    @property
    def api_version(self) -> str:
        return API_VERSION

    @property
    def app_version(self) -> str:
        return _Version.app_version()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def schema_version(self) -> int:
        return _Schema.VERSION

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self._settings.set(key, value)

    def reset_setting(self, key: str) -> None:
        self._settings.reset(key)

    def _policy(self) -> Policy | None:
        if self._policy_source is not None:
            return self._policy_source()
        try:
            directory = _Paths.policy_dir(self._db_path, create=False)
            return _PolicyClient(directory, logger=logging.getLogger("vethuq.policy")).current().policy
        except Exception:  # noqa: BLE001 - a policy problem never blocks an add-on
            return None

    def revoked_licence_ids(self) -> frozenset[str]:
        policy = self._policy()
        return frozenset(policy.revoked_licence_ids) if policy is not None else frozenset()

    def addon_policy_enabled(self) -> bool:
        policy = self._policy()
        entry = policy.addons.get(self._addon_id) if policy is not None else None
        return entry.enabled if entry is not None else True

    def release_database(self) -> None:
        self._release()

    def log(self, level: int, message: str) -> None:
        _DatabaseLog.logger().log(level, "addon %s: %s", self._addon_id, message)
