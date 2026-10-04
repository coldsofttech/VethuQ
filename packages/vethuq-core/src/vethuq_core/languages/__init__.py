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

__all__ = ["Languages", "Script", "Scripts"]


def __getattr__(name: str) -> Any:
    if name == "Languages":
        from vethuq_core.languages.languages import Languages

        return Languages
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
