"""GPU-related settings."""

from __future__ import annotations

import sqlite3

from vethuq_core.settings.settings import Settings


class GpuSettings:
    KEY = "gpu_enabled"

    @staticmethod
    def is_enabled(conn: sqlite3.Connection) -> bool:
        """Whether OCR should attempt to use the GPU. Disabled by default."""
        return Settings.get(conn, GpuSettings.KEY) == "true"

    @staticmethod
    def set_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
        Settings.set(conn, GpuSettings.KEY, "true" if enabled else "false")
