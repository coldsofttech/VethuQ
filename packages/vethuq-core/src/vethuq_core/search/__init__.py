"""Searching indexed content, and exporting the results.

The names below are imported on first use (PEP 562) rather than here, so that the database
layer can import `vethuq_core.search.normalizers` - which it needs to record a page's
normalized text - without pulling in the engines, which import the database layer.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vethuq_core.search.engines import PageResult, SearchQueryError
    from vethuq_core.search.export import Export
    from vethuq_core.search.search import (
        FileMatch,
        Search,
        SearchMatch,
        SearchOptionError,
        SearchOptions,
    )

_EXPORTS = {
    "Export": "vethuq_core.search.export",
    "FileMatch": "vethuq_core.search.search",
    "PageResult": "vethuq_core.search.engines",
    "Search": "vethuq_core.search.search",
    "SearchMatch": "vethuq_core.search.search",
    "SearchOptionError": "vethuq_core.search.search",
    "SearchOptions": "vethuq_core.search.search",
    "SearchQueryError": "vethuq_core.search.engines",
}

__all__ = [
    "Export",
    "FileMatch",
    "PageResult",
    "Search",
    "SearchMatch",
    "SearchOptionError",
    "SearchOptions",
    "SearchQueryError",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
