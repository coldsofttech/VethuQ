"""Internal search: the index, the engines and normalizers, and running a search. The public view
is `vethuq.search`."""

from __future__ import annotations

from vethuq._search.engines import ALL, AUTO, HYBRID, _Engines, _EngineView
from vethuq._search.index import _SearchIndex
from vethuq._search.service import _Match, _Outcome, _Search, _Synced

__all__ = [
    "ALL",
    "AUTO",
    "HYBRID",
    "_Engines",
    "_EngineView",
    "_Match",
    "_Outcome",
    "_Search",
    "_SearchIndex",
    "_Synced",
]
