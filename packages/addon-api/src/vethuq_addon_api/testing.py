"""A stand-in host for testing an add-on without VethuQ."""

from __future__ import annotations

import logging
from pathlib import Path

from vethuq_addon_api.api import API_VERSION


class FakeHost:
    """Implements `Host` in memory. Tests can read `settings`, `logs` and `released`."""

    def __init__(
        self,
        db_path: Path,
        schema_version: int = 1,
        app_version: str = "0.0.0",
        revoked: frozenset[str] = frozenset(),
        enabled: bool = True,
    ) -> None:
        self._db_path = Path(db_path)
        self._schema_version = schema_version
        self._app_version = app_version
        self._revoked = revoked
        self._enabled = enabled
        self.settings: dict[str, str] = {}
        self.logs: list[tuple[int, str]] = []
        self.released = 0

    @property
    def api_version(self) -> str:
        return API_VERSION

    @property
    def app_version(self) -> str:
        return self._app_version

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def schema_version(self) -> int:
        return self._schema_version

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    def reset_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    def revoked_licence_ids(self) -> frozenset[str]:
        return self._revoked

    def addon_policy_enabled(self) -> bool:
        return self._enabled

    def release_database(self) -> None:
        self.released += 1

    def log(self, level: int, message: str) -> None:
        self.logs.append((level, message))
        logging.getLogger("vethuq.addon.fake").log(level, message)
