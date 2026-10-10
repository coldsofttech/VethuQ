"""Add-ons: `VethuQ().addons`.

Add-ons are separate packages that VethuQ finds once they are installed. Their public classes are
imported from here:

    from vethuq.addons.backup import Backup

VethuQ itself deploys no add-on and works the same without them. If an add-on isn't installed,
importing from it raises `ModuleNotFoundError`; `client.addons.is_installed("backup")` asks first.
"""

from __future__ import annotations

from vethuq._addons import _AddonFinder
from vethuq.addons.manage import AddonInfo, Addons, AddonSettings
from vethuq.enums import AddonStatus

_AddonFinder.install()

__all__ = ["AddonInfo", "AddonSettings", "AddonStatus", "Addons"]
