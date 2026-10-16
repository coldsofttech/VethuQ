"""Bundles of add-ons: `VethuQ().bundles`.

A bundle brings several add-ons in under one name, and one licence can list the bundle instead of
every add-on in it. This is the same view as `VethuQ().addons`, a bundle at a time.

    client.bundles.list()                       # each bundle, with which of its add-ons are here
    client.bundles.get("office")                # one bundle, or None
    client.bundles.is_installed("office")       # every add-on of it is installed
    client.bundles.set_enabled("office", False) # turn all of its installed add-ons off
    client.bundles.install_licence(token)       # store a licence that lists a bundle
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vethuq.addons import Addons
    from vethuq.catalog import BundleEntry, CatalogClient

__all__ = ["Bundles"]


class Bundles:
    """The bundles in the catalog, and what is installed of each.

    Not created directly: use `VethuQ().bundles`.
    """

    def __init__(self, addons: Addons, catalog: Callable[[], CatalogClient]) -> None:
        self._addons = addons
        self._catalog = catalog

    def list(self, language: str | None = None) -> list[BundleEntry]:
        """Every bundle in the catalog (or the built-in baseline), with which of its add-ons are
        installed here. `language` (`es`, `es-MX`) picks translated text. Makes no request."""
        return self._catalog().bundles(language)

    def get(self, bundle_id: str, language: str | None = None) -> BundleEntry | None:
        """One bundle, or None if the catalog doesn't list it."""
        return self._catalog().get_bundle(bundle_id, language)

    def is_installed(self, bundle_id: str) -> bool:
        """Whether every add-on of the bundle is installed. False for a bundle that isn't listed."""
        entry = self.get(bundle_id)
        return entry is not None and entry.complete

    def set_enabled(self, bundle_id: str, enabled: bool) -> BundleEntry:
        """Turn every installed add-on of the bundle off or on, like `Addons.set_enabled` does for
        one. The change applies the next time VethuQ starts. Add-ons of the bundle that aren't
        installed are left out. Raises `ValueError` for a bundle that isn't listed, one with no
        installed add-on, or an add-on that can't be turned off (nothing is changed then)."""
        entry = self.get(bundle_id)
        if entry is None:
            raise ValueError(f"No bundle {bundle_id!r} is listed.")
        if not entry.installed:
            raise ValueError(f"No add-on of the {bundle_id} bundle is installed.")
        if not enabled:
            locked = [a for a in entry.installed if a in self._addons.ALWAYS_ON]
            if locked:
                raise ValueError(f"{', '.join(locked)} can't be turned off: VethuQ needs it.")
        for addon_id in entry.installed:
            self._addons.set_enabled(addon_id, enabled)
        return self.get(bundle_id) or entry

    def install_licence(self, token: str, github_owner_id: int | None = None) -> list[Any]:
        """Store a licence token as the licence of every installed add-on it lists, which includes
        the add-ons of a bundle it names (see `client.licences.install`). Returns what happened
        for each add-on."""
        return self._addons.install_licence(token, github_owner_id)
