"""Search for the interface: the engines and what they take, running a search, exporting it."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

MAX_LIMIT = 500
DEFAULT_LIMIT = 50


def _words(value: object, name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{name} is a list of words.")
    return value


def _numbers(value: object, name: str) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(
        isinstance(v, int) and not isinstance(v, bool) for v in value
    ):
        raise ValueError(f"{name} is a list of whole numbers.")
    return value


def _mapping(value: object, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ValueError(f"{name} is an object.")
    return value


def _number(value: object, name: str, default: int | None, low: int = 0) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ValueError(f"{name} is a whole number of {low} or more.")
    return value


class SearchService:
    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client

    # ----- what can be asked ------------------------------------------------------------------

    def options(self) -> dict[str, object]:
        """The engines, normalizers and file types installed, and the defaults a search starts
        from (the Search settings)."""
        client = self._client()
        return {
            "engines": [e.to_dict() for e in client.search.engines()],
            "normalizers": [n.to_dict() for n in client.search.normalizers()],
            "file_types": [t.to_dict() for t in client.file_types.list() if t.available],
            "defaults": {
                "engine": client.settings.search.get_engine(),
                "context_chars": client.settings.search.get_snippet_context_chars(),
            },
        }

    # ----- running ----------------------------------------------------------------------------

    @staticmethod
    def arguments(body: Mapping[str, Any]) -> dict[str, Any]:
        """What `search.run` takes, from what the interface sent (and checked)."""
        query = body.get("query", "")
        if not isinstance(query, str):
            raise ValueError("query is text.")
        case = body.get("case_sensitive")
        if case is not None and not isinstance(case, bool):
            raise ValueError("case_sensitive is true or false.")
        for name in ("engine", "combine", "sort"):
            if body.get(name) is not None and not isinstance(body[name], str):
                raise ValueError(f"{name} is a word.")
        return {
            "query": query,
            "engine": body.get("engine") or None,
            "case_sensitive": case,
            "context_chars": _number(body.get("context_chars"), "context_chars", None),
            "languages": _words(body.get("languages"), "languages") or None,
            "file_types": _words(body.get("file_types"), "file_types") or None,
            "sources": _numbers(body.get("sources"), "sources") or None,
            "normalize": _mapping(body.get("normalize"), "normalize") or None,
            "options": _mapping(body.get("options"), "options") or None,
            "combine": body.get("combine") or None,
            "sort": body.get("sort") or None,
            "order": body.get("order") or "asc",
        }

    def run(self, body: Mapping[str, Any]) -> dict[str, object]:
        arguments = self.arguments(body)
        limit = min(_number(body.get("limit"), "limit", DEFAULT_LIMIT), MAX_LIMIT)  # type: ignore[type-var]
        offset = _number(body.get("offset"), "offset", 0)
        result = self._client().search.run(**arguments, limit=limit, offset=offset)
        data = result.to_dict()
        data["limit"] = limit
        data["offset"] = offset
        return data

    def export(self, body: Mapping[str, Any], fmt: str | None) -> tuple[bytes, str, str]:
        """Every match of a search (not just a page of it) as a JSON or HTML file."""
        arguments = self.arguments(body)
        client = self._client()
        result = client.search.run(**arguments)
        fmt = (fmt or "json").lower()
        if fmt not in ("json", "html"):
            raise ValueError("format is json or html.")
        with tempfile.TemporaryDirectory(prefix="vethuq-search-") as folder:
            target = Path(folder) / f"search-results.{fmt}"
            written = Path(client.search.export(result, target, fmt))
            mime = "text/html" if written.suffix == ".html" else "application/json"
            return written.read_bytes(), written.name, mime
