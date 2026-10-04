"""GPU-related settings."""

from __future__ import annotations

from vethuq_core.settings.settings import Settings
from vethuq_core.storage import Storage


class GpuSettings:
    KEY = "gpu_enabled"
    DEFAULT_ENABLED = False

    @staticmethod
    def is_enabled(storage: Storage) -> bool:
        """Whether OCR should attempt to use the GPU. Disabled by default."""
        return Settings.get(storage, GpuSettings.KEY) == "true"

    @staticmethod
    def set_enabled(storage: Storage, enabled: bool) -> None:
        Settings.set(storage, GpuSettings.KEY, "true" if enabled else "false")

    @staticmethod
    def reset(storage: Storage) -> None:
        """Back to the default: GPU use disabled."""
        GpuSettings.set_enabled(storage, GpuSettings.DEFAULT_ENABLED)
