"""The update check: is a newer VethuQ out, and which features need one.

The signed policy is the only source of `latest` and `minimum_supported`; there is no fallback to
PyPI or GitHub. Importing this package does no I/O and no network.
"""

from vethuq_core.updates.checker import UpdateChecker
from vethuq_core.updates.distribution import Distribution
from vethuq_core.updates.features import FeatureAccess, FeatureGate
from vethuq_core.updates.result import UpdateResult, UpdateStatus
from vethuq_core.updates.versions import Versions

__all__ = [
    "Distribution",
    "FeatureAccess",
    "FeatureGate",
    "UpdateChecker",
    "UpdateResult",
    "UpdateStatus",
    "Versions",
]
