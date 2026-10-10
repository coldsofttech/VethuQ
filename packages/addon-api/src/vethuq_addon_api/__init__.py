"""The contract between VethuQ and its add-ons."""

from __future__ import annotations

from vethuq_addon_api.api import API_VERSION, Addon, Hook, Host, Manifest, MigrationInfo
from vethuq_addon_api.errors import AddonError, AddonLicenceError

ENTRY_POINT_GROUP = "vethuq.addons"

__all__ = [
    "API_VERSION",
    "ENTRY_POINT_GROUP",
    "Addon",
    "AddonError",
    "AddonLicenceError",
    "Hook",
    "Host",
    "Manifest",
    "MigrationInfo",
]
