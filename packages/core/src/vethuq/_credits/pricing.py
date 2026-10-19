"""What a page costs (see docs/credits.md, section 4)."""

from __future__ import annotations

import math

from vethuq._credits.terms import _Terms, milli

A4_AREA_PT = 595.276 * 841.89  # points squared
BUCKETS = ((0.25, "xs"), (0.5, "s"), (1.0, "m"), (2.0, "l"), (math.inf, "xl"))


class _PageTooLarge(Exception):
    """A page bigger than the rate card allows (larger than A0)."""


class _Pricing:
    def __init__(self, terms: _Terms) -> None:
        self.terms = terms

    def size_factor(self, width_pt: float | None, height_pt: float | None) -> float:
        """The page area against A4, reduced by the tolerance, rounded up to the step; at least
        the minimum. An unknown size counts as A4. Raises `_PageTooLarge` above the maximum."""
        t = self.terms
        if not width_pt or not height_pt or width_pt <= 0 or height_pt <= 0:
            return 1.0
        ratio = width_pt * height_pt / A4_AREA_PT * (1 - t.tolerance_percent / 100)
        factor = max(math.ceil(round(ratio / t.step, 9)) * t.step, t.minimum)
        if factor > t.per_page_max:
            raise _PageTooLarge(f"The page is too large ({width_pt:.0f} x {height_pt:.0f} pt).")
        return round(factor, 6)

    @staticmethod
    def bucket(factor: float) -> str:
        return next(name for limit, name in BUCKETS if factor <= limit)

    def cost_milli(
        self,
        factor: float,
        *,
        additional_language: bool = False,
        covered: float = 1.0,
        device: str = "cpu",
    ) -> int:
        """The cost of reading a page: `factor` x the pass rate x the device and model
        multipliers. `covered` is the share of the page read (images only, on a mixed page): the
        cost is that share of the page, but never less than the minimum nor more than the page."""
        t = self.terms
        rate = t.language_pass if additional_language else t.quick
        full = factor * rate * t.device_factor(device) * t.fast
        if covered >= 1.0:
            return milli(full)
        return milli(min(full, max(full * covered, t.minimum)))

    def native_milli(
        self,
        factor: float,
        file_type: str | None,
        *,
        covered: float = 0.0,
        blank: bool = False,
    ) -> int:
        """The cost of a page read from the file's own text: `factor` x the quick rate x the
        native share of the file type. `covered` is the share of the page its images cover (read
        by OCR and priced by `cost_milli`), so only the rest is native. No OCR runs, so the
        device and model multipliers don't apply. A blank page costs the minimum at most."""
        t = self.terms
        cost = milli(factor * t.quick * t.native_rate(file_type) * max(1.0 - covered, 0.0))
        return min(cost, milli(t.minimum)) if blank else cost

    def rotated_milli(
        self, factor: float, passes: int, *, covered: float = 1.0, device: str = "cpu"
    ) -> int:
        """The cost of reading a page at `passes` rotated angles (the deeper phases): each pass is
        `factor` x the rotated rate x the device and model multipliers. `covered` is the share of
        the page read (images only), as for `cost_milli`."""
        t = self.terms
        one = factor * t.rotated_factor * t.device_factor(device) * t.advanced
        if covered < 1.0:
            one = min(one, max(one * covered, t.minimum))
        return milli(one * passes)

    def blank_milli(self, charged_milli: int) -> int:
        """A page that turned out to be blank costs the minimum only."""
        return min(charged_milli, milli(self.terms.minimum))
