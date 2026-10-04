"""Writing systems and the languages written in them.

OCR, normalization and search ask this package what a piece of text *is* (which scripts it
contains, which enabled languages can read it) instead of naming a language themselves, so
nothing outside it needs a per-language condition.

`Scripts` has no dependencies, so the database layer and the normalizers can import it freely;
`Languages` reads the OCR catalog and is loaded on first use, so importing this package never
pulls the OCR package in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vethuq_core.languages.scripts import Script, Scripts

if TYPE_CHECKING:
    from vethuq_core.languages.languages import Languages
    from vethuq_core.languages.selection import Candidates, LanguageSelection, UnknownLanguageError

__all__ = [
    "Candidates",
    "LanguageSelection",
    "Languages",
    "Script",
    "Scripts",
    "UnknownLanguageError",
]


def __getattr__(name: str) -> Any:
    if name == "Languages":
        from vethuq_core.languages.languages import Languages

        return Languages
    if name in ("Candidates", "LanguageSelection", "UnknownLanguageError"):
        from vethuq_core.languages import selection

        return getattr(selection, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
