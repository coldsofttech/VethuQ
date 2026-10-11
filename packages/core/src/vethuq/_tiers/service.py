"""The processing tiers: which exist, which can be used, and which a run uses."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from vethuq._errors import _TierUnavailableError
from vethuq.enums import ProcessingTier
from vethuq_addon_api import OcrExecutor, TierSpec

LOCAL, GITHUB, HYBRID = (t.value for t in ProcessingTier)
_logger = logging.getLogger("vethuq.tiers")


@dataclass(frozen=True)
class _TierView:
    id: str
    label: str
    wallet: str
    available: bool
    reason: str
    executor: OcrExecutor | None
    asynchronous: bool = False


class _Tiers:
    def __init__(self, specs: Callable[[], list[TierSpec]], local: OcrExecutor) -> None:
        self._specs = specs
        self._local = local

    def views(self) -> list[_TierView]:
        """Every tier VethuQ knows: local, the ones add-ons provide, and hybrid (which needs
        GitHub)."""
        views = [_TierView(LOCAL, "Local", LOCAL, True, "", self._local)]
        for spec in self._specs():
            if spec.id in (LOCAL, HYBRID):
                _logger.warning("An add-on tried to provide the reserved tier %r", spec.id)
                continue
            executor = spec.executor
            available = spec.available and executor is not None
            reason = "" if available else (spec.reason or "it has no executor")
            views.append(
                _TierView(
                    spec.id,
                    spec.label,
                    spec.wallet,
                    available,
                    reason,
                    executor,
                    bool(executor and executor.asynchronous),
                )  # fmt: skip
            )
        github = next((v for v in views if v.id == GITHUB), None)
        if github is None:
            hybrid = _TierView(HYBRID, "Hybrid", LOCAL, False, "it needs the GitHub tier", None)
        elif not github.available:
            hybrid = _TierView(
                HYBRID,
                "Hybrid",
                LOCAL,
                False,
                f"the GitHub tier isn't ready: {github.reason}",
                None,
            )
        else:
            hybrid = _TierView(HYBRID, "Hybrid", LOCAL, True, "", None, True)
        views.append(hybrid)
        return views

    def get(self, tier: str) -> _TierView | None:
        return next((v for v in self.views() if v.id == tier), None)

    def hybrid_parts(self) -> tuple[_TierView, _TierView]:
        """(local, GitHub) as hybrid uses them. Only for a hybrid run, which `resolve` has
        already checked can run."""
        local, github = self.get(LOCAL), self.get(GITHUB)
        assert local is not None and github is not None  # noqa: S101 - resolve() guarantees it
        return local, github

    def known(self) -> str:
        return ", ".join(v.id for v in self.views())

    def resolve(self, tier: str | None, default: str) -> _TierView:
        """The tier a run uses: the one asked for, else the default. Raises
        `TierUnavailableError` if it isn't known, isn't ready, or can't run yet."""
        wanted = default if tier is None else tier
        if not isinstance(wanted, str):
            raise TypeError("A tier is its id, for example 'local'.")
        view = self.get(wanted.strip().lower())
        if view is None:
            raise _TierUnavailableError(
                f"There is no processing tier {wanted!r}.", f"Tiers: {self.known()}."
            )
        if not view.available:
            raise _TierUnavailableError(
                f"The {view.label} tier can't be used: {view.reason}.",
                "Use client.tiers.list() to see what is available, or run with tier='local'.",
            )
        return view
