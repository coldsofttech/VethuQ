"""Search for the interface: the engines and what they take, running a search, exporting it."""

from __future__ import annotations

import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

MAX_LIMIT = 500
DEFAULT_LIMIT = 50
# The text viewer: which files it shows, how many lines it hands out at once, how much of a line it
# keeps (a minified file can be one line of megabytes), and how long a file's lines stay split.
TEXT_TYPES = frozenset({"txt", "markdown"})
TEXT_MAX_LINES = 500
TEXT_DEFAULT_LINES = 200
TEXT_LINE_CLIP = 10_000
TEXT_KEEP_SECONDS = 60.0
TEXT_KEEP_FILES = 3


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


def _whole(value: object, name: str) -> object:
    """A query-string value as a whole number (anything else is left for `_number` to refuse)."""
    try:
        return int(str(value))
    except ValueError:
        raise ValueError(f"{name} is a whole number.") from None


class SearchService:
    def __init__(self, client: Callable[[], Any]) -> None:
        self._client = client
        self._texts: dict[tuple[int, int], tuple[float, Any, list[str]]] = {}
        self._texts_lock = threading.Lock()

    # ----- the text of a file, a window of lines at a time ------------------------------------

    def _lines_of(self, document_id: int, page_number: int) -> tuple[Any, list[str]]:
        key = (document_id, page_number)
        now = time.monotonic()
        with self._texts_lock:
            kept = self._texts.get(key)
            if kept is not None and now - kept[0] < TEXT_KEEP_SECONDS:
                return kept[1], kept[2]
        page = self._client().search.page_text(document_id, page_number)
        if page is None:
            raise LookupError("That page is not in the index.")
        if page.file_type not in TEXT_TYPES:
            raise ValueError("Only the text of a text or Markdown file can be shown here.")
        lines = [line.removesuffix("\r") for line in page.text.split("\n")]
        with self._texts_lock:
            self._texts[key] = (now, page, lines)
            for old in sorted(self._texts, key=lambda k: self._texts[k][0])[:-TEXT_KEEP_FILES]:
                del self._texts[old]
        return page, lines

    def text_window(self, query: Mapping[str, Any]) -> dict[str, object]:
        """`count` lines of a stored text from line `start` (0-based), and how many lines there are.
        What is stored is what a search matched, so a match's line and column count in it."""
        query = {k: _whole(v, k) for k, v in query.items()}
        document_id = _number(query.get("document_id"), "document_id", None, 1)
        if document_id is None:
            raise ValueError("document_id is a whole number of 1 or more.")
        page_number = _number(query.get("page"), "page", 1, 1)
        start = _number(query.get("start"), "start", 0)
        count = min(_number(query.get("count"), "count", TEXT_DEFAULT_LINES, 1), TEXT_MAX_LINES)
        page, lines = self._lines_of(document_id, page_number)
        window = [
            line if len(line) <= TEXT_LINE_CLIP else line[:TEXT_LINE_CLIP] + "…"
            for line in lines[start : start + count]
        ]
        return {
            "total": len(lines),
            "start": start,
            "lines": window,
            "file_name": page.file_name,
            "file_path": page.file_path,
            "file_type": page.file_type,
            "clip": TEXT_LINE_CLIP,
        }

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
