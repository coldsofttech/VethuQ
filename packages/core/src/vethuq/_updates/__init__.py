"""Internal update check; the public view is `vethuq.updates`."""

from __future__ import annotations

from vethuq._updates.checker import _FeatureGate, _UpdateChecker
from vethuq._updates.distribution import _Distribution
from vethuq._updates.model import FeatureAccess, UpdateResult
from vethuq._updates.versions import _Versions

__all__ = [
    "FeatureAccess",
    "UpdateResult",
    "_Distribution",
    "_FeatureGate",
    "_UpdateChecker",
    "_Versions",
]
