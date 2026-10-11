"""Processing tiers: where the pages that need OCR are read: `VethuQ().tiers`.

VethuQ always extracts a file's pages and decides, on this computer, which need OCR. A tier decides
where that OCR runs:

- `local`: on this computer. Always there, and the default.
- `github`: in your own GitHub account (the GitHub add-on). Only the pages that need OCR are sent,
  encrypted.
- `hybrid`: local first, with the pages the settings pick (large ones, and later the deeper OCR
  phases) sent to GitHub; a page GitHub can't take is read here.

Each tier pays from its own credit wallet (see `credits`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vethuq._db import _Database
from vethuq._errors import _TierUnavailableError
from vethuq._settings import _TierSettings
from vethuq._tiers import _Tiers
from vethuq.enums import ProcessingTier

__all__ = ["ProcessingTier", "TierInfo", "Tiers"]


@dataclass(frozen=True)
class TierInfo:
    """A processing tier."""

    id: str  # for example "local"
    label: str  # "Local"
    wallet: str  # the credit wallet its work is paid from
    available: bool  # can be used now
    reason: str  # why it can't, when it can't
    selected: bool  # it is the default tier
    remote: bool  # its work is done elsewhere and finishes later

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    def to_json(self, indent: int | None = None) -> str:
        """The same details as `to_dict()`, as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class Tiers:
    """The processing tiers and the choice of the default.

    Not created directly: use `VethuQ().tiers`. A run can name its own tier
    (`index.run(tier="github")`); otherwise the default applies.
    """

    def __init__(self, database: _Database, tiers: _Tiers) -> None:
        self._database = database
        self._tiers = tiers

    def _default(self) -> str:
        with self._database.session() as session:
            return _TierSettings.get_default(session)

    def list(self) -> list[TierInfo]:
        """Every tier VethuQ knows, with whether it can be used now: local first, then the
        tiers add-ons provide, then hybrid."""
        default = self._default()
        return [
            TierInfo(
                v.id, v.label, v.wallet, v.available, v.reason, v.id == default, v.asynchronous
            )
            for v in self._tiers.views()
        ]

    def get(self, tier: str) -> TierInfo | None:
        """One tier by id, or None if VethuQ doesn't know it."""
        wanted = str(tier).strip().lower()
        return next((t for t in self.list() if t.id == wanted), None)

    def current(self) -> TierInfo:
        """The default tier. It may be unavailable (for example its add-on was removed): a run
        then raises `TierUnavailableError`."""
        default = self._default()
        found = self.get(default)
        return found if found is not None else self.get("local")  # type: ignore[return-value]

    def use(self, tier: str | ProcessingTier) -> TierInfo:
        """Make `tier` the default. It must be one VethuQ knows (`list()`), but may be
        unavailable for now. Raises `TierUnavailableError` for an unknown id."""
        wanted = str(tier.value if isinstance(tier, ProcessingTier) else tier).strip().lower()
        if self._tiers.get(wanted) is None:
            raise _TierUnavailableError(
                f"There is no processing tier {wanted!r}.", f"Tiers: {self._tiers.known()}."
            )
        with self._database.session() as session:
            _TierSettings.set_default(session, wanted)
        return self.current()

    def reset(self) -> TierInfo:
        """Go back to the local tier as the default."""
        with self._database.session() as session:
            _TierSettings.reset_default(session)
        return self.current()
