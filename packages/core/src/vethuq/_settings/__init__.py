"""Internal settings service; the public view is `vethuq.settings`."""

from __future__ import annotations

from vethuq._settings.settings import _Settings, _SourceSettings

__all__ = ["_Settings", "_SourceSettings"]
