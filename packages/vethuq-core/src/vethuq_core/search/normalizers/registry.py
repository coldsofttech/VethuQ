"""Normalizer registry: which `Normalizer` implementations exist and how they're applied."""

from __future__ import annotations

from collections.abc import Mapping

from vethuq_core.search.normalizers.base import Normalizer
from vethuq_core.search.normalizers.common import Pipeline


class Normalizers:
    # The order they are applied in: Unicode first (so the rest see settled characters), then
    # case, then look-alikes (which read letters of either case).
    ORDER = ("unicode", "case", "leetspeak")

    _normalizers: dict[str, Normalizer] = {}

    @staticmethod
    def register(normalizer: Normalizer) -> None:
        """Make a normalizer available under its name, replacing any existing one."""
        Normalizers._normalizers[normalizer.name] = normalizer

    @staticmethod
    def get(name: str) -> Normalizer:
        try:
            return Normalizers._normalizers[name]
        except KeyError:
            raise ValueError(
                f"Unknown normalizer {name!r}; available: {sorted(Normalizers._normalizers)}"
            ) from None

    @staticmethod
    def available() -> list[str]:
        """Names of the registered normalizers, in the order they are applied."""
        known = set(Normalizers._normalizers)
        ordered = [name for name in Normalizers.ORDER if name in known]
        return ordered + sorted(known - set(ordered))

    @staticmethod
    def index_form(text: str) -> str:
        """`text` through every normalizer's `index_form`, in application order: the form the
        database records (`norm_text`) so candidate pages can be found through an index."""
        for name in Normalizers.available():
            text = Normalizers.get(name).index_form(text)
        return text

    # The normalizations that can make a match differ from what was typed, and what to call them.
    MODIFIERS = ("accents", "look-alike")

    @staticmethod
    def applied(query: str, matched: str) -> tuple[str, ...]:
        """The normalizations `matched` needed to count as `query`, from `MODIFIERS` (empty when
        it is the text as typed: case and the way an accent is encoded don't count)."""
        import unicodedata

        def settled(text: str) -> str:
            return unicodedata.normalize("NFC", text).casefold()

        def accents(text: str) -> str:
            return Normalizers.get("unicode").fold(text, "full").text.casefold()

        def lookalikes(text: str) -> str:
            return Normalizers.get("leetspeak").fold(text, "extended").text

        typed, found = settled(query), settled(matched)
        if typed == found:
            return ()
        if lookalikes(typed) == lookalikes(found):
            return ("look-alike",)
        if accents(typed) == accents(found):
            return ("accents",)
        if lookalikes(accents(typed)) == lookalikes(accents(found)):
            return ("accents", "look-alike")
        return ()

    @staticmethod
    def pipeline(levels: Mapping[str, str]) -> Pipeline:
        """The normalizers named in `levels`, at those levels, in application order.

        Raises `ValueError` for an unknown normalizer or a level it doesn't have.
        """
        steps = []
        for name in Normalizers.available():
            if name not in levels:
                continue
            normalizer = Normalizers.get(name)
            if levels[name] not in normalizer.levels:
                raise ValueError(
                    f"{name} must be one of {', '.join(normalizer.levels)}, not {levels[name]!r}"
                )
            steps.append((normalizer, levels[name]))
        unknown = set(levels) - {normalizer.name for normalizer, _ in steps}
        if unknown:
            raise ValueError(f"Unknown normalizer {sorted(unknown)[0]!r}")
        return Pipeline(steps)
