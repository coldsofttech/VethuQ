"""Internal update check; the public view is `vethuq.updates`."""

from __future__ import annotations

from vethuq._updates.checker import _FeatureGate, _UpdateChecker
from vethuq._updates.distribution import _Distribution
from vethuq._updates.install import InstallKind, UpgradeHelp, _Install
from vethuq._updates.installer import InstallerDownload, InstallerError, _Installer
from vethuq._updates.model import FeatureAccess, UpdateResult
from vethuq._updates.versions import _Versions

__all__ = [
    "FeatureAccess",
    "InstallKind",
    "InstallerDownload",
    "InstallerError",
    "_Installer",
    "UpgradeHelp",
    "_Install",
    "UpdateResult",
    "_Distribution",
    "_FeatureGate",
    "_UpdateChecker",
    "_Versions",
]
