"""Sources for the interface: the list, adding and removing, and the files of a source (scanned
once, kept for a short while, then filtered, sorted and paged here, because the core lists every
file of a folder in one go)."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

CACHE_SECONDS = 15.0
_FILE_SORTS = {
    "name": lambda f: f["name"].casefold(),
    "path": lambda f: f["relative_path"].casefold(),
    "size": lambda f: f["size_bytes"] or 0,
    "modified": lambda f: f["modified_at"] or "",
    "status": lambda f: f["status"],
    "type": lambda f: f["file_type"] or "",
    "pages": lambda f: f["pages"] or 0,
    "confidence": lambda f: f["confidence"] if f["confidence"] is not None else -1,
}
_MIMES = {"json": "application/json", "html": "text/html"}


def source_dict(source: Any) -> dict[str, object]:
    """A source as the interface shows it."""
    path = source.path
    return {
        "id": source.id,
        "path": path,
        "name": os.path.basename(path.rstrip("\\/")) or path,
        "parent": os.path.dirname(path.rstrip("\\/")),
        "type": source.source_type.value if source.source_type else None,
        "status": source.status.value if source.status else None,
        "languages": list(source.languages) if source.languages else None,
        "added_at": source.added_at,
        "last_scanned_at": source.last_scanned_at,
        "removed_at": source.removed_at,
        "active": bool(source.is_active),
        "files_total": source.files_total,
        "files_processed": source.files_processed,
        "missing": not os.path.exists(path),
    }


def file_dict(item: Any) -> dict[str, object]:
    """A file of a source, with where it is in indexing."""
    index = item.index
    data: dict[str, object] = {
        "path": item.path,
        "relative_path": item.relative_path,
        "name": item.name,
        "size_bytes": item.size_bytes,
        "modified_at": item.modified_at,
        "status": None,
        "file_type": None,
        "protected": False,
    }
    if index is not None:
        data.update(
            status=index.status.value,
            file_type=index.file_type,
            error=index.error,
            sha256=index.sha256,
            indexed_at=index.indexed_at,
            retry_count=index.retry_count,
            duplicate_of=index.duplicate_of,
            pages=index.pages,
            confidence=index.confidence,
            languages=index.languages,
            low_confidence_pages=index.low_confidence_pages,
            band=index.band.value if index.band else None,
            on_disk=index.on_disk,
            # A kind of file an add-on reads, yet unsupported: the file needs a password.
            protected=index.status.value == "unsupported" and index.file_type is not None,
        )
    return data


class SourcesService:
    """Sources, on the core client `client()` returns."""

    def __init__(self, client: Callable[[], Any], ttl: float = CACHE_SECONDS) -> None:
        self._client = client
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[int, tuple[float, list[Any], list[dict[str, object]]]] = {}

    def forget(self, source_id: int | None = None) -> None:
        with self._lock:
            if source_id is None:
                self._cache.clear()
            else:
                self._cache.pop(source_id, None)

    # ----- sources ----------------------------------------------------------------------------

    def list(
        self,
        *,
        removed: bool = False,
        status: str | None = None,
        source_type: str | None = None,
        language: str | None = None,
        q: str = "",
        sort: str = "id",
        order: str = "asc",
    ) -> list[dict[str, object]]:
        rows = self._client().sources.list(
            include_removed=removed,
            status=status or None,
            source_type=source_type or None,
            language=language or None,
            sort_by=sort,
            order=order,
        )
        needle = q.strip().casefold()
        return [source_dict(row) for row in rows if not needle or needle in row.path.casefold()]

    def get(self, source_id: int) -> dict[str, object]:
        return source_dict(self._client().sources.get(source_id, include_removed=True))

    def add(self, path: str, languages: list[str] | None = None) -> dict[str, object]:
        source = self._client().sources.create(path, languages=languages or None)
        self.forget()
        return source_dict(source)

    def remove(self, source_id: int) -> dict[str, object]:
        source = self._client().sources.remove(source_id)
        self.forget(source_id)
        return source_dict(source)

    def restore(self, source_id: int) -> dict[str, object]:
        """Add a removed source again (the core reactivates it) with the languages it had."""
        old = self._client().sources.get(source_id, include_removed=True)
        source = self._client().sources.create(old.path, languages=old.languages)
        self.forget()
        return source_dict(source)

    def purge(self, source_id: int) -> dict[str, object]:
        result = self._client().sources.purge(source_id)
        self.forget(source_id)
        return {"id": result.id, "path": result.path}

    def set_languages(self, source_id: int, languages: list[str] | None) -> dict[str, object]:
        source = self._client().sources.set_languages(source_id, languages or None)
        return source_dict(source)

    # ----- files ------------------------------------------------------------------------------

    def _scan(self, source_id: int, refresh: bool) -> tuple[float, list[dict[str, object]]]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(source_id)
        if hit is not None and not refresh and now - hit[0] < self._ttl:
            return hit[0], hit[2]
        items = self._client().sources.list_files(source_id, detailed=True)
        rows = [file_dict(item) for item in items]
        with self._lock:
            self._cache[source_id] = (now, items, rows)
        return now, rows

    def files(
        self,
        source_id: int,
        *,
        q: str = "",
        status: str | None = None,
        file_type: str | None = None,
        band: str | None = None,
        min_confidence: float | None = None,
        sort: str = "path",
        order: str = "asc",
        offset: int = 0,
        limit: int = 200,
        refresh: bool = False,
    ) -> dict[str, object]:
        """One page of a source's files, with how many files each status and type has."""
        if sort not in _FILE_SORTS:
            raise ValueError(f"sort is one of {', '.join(_FILE_SORTS)}.")
        if order not in ("asc", "desc"):
            raise ValueError("order is asc or desc.")
        _, rows = self._scan(source_id, refresh)
        facets = {
            "status": self._count(rows, "status"),
            "type": self._count(rows, "file_type"),
        }
        matching = self._filter(rows, q, status, file_type, band, min_confidence)
        matching = sorted(matching, key=_FILE_SORTS[sort], reverse=order == "desc")
        return {
            "total": len(matching),
            "all": len(rows),
            "offset": offset,
            "items": matching[offset : offset + limit],
            "facets": facets,
        }

    @staticmethod
    def _count(rows: list[dict[str, object]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            name = str(row[key]) if row[key] else "unsupported" if key == "file_type" else "none"
            counts[name] = counts.get(name, 0) + 1
        return counts

    @staticmethod
    def _filter(
        rows: list[dict[str, object]],
        q: str,
        status: str | None,
        file_type: str | None,
        band: str | None,
        min_confidence: float | None,
    ) -> list[dict[str, object]]:
        needle = q.strip().casefold()
        keep = []
        for row in rows:
            if needle and needle not in str(row["relative_path"]).casefold():
                continue
            if status and row["status"] != status:
                continue
            if file_type and (row["file_type"] or "unsupported") != file_type:
                continue
            if band and row.get("band") != band:
                continue
            if min_confidence is not None and (
                row.get("confidence") is None or row["confidence"] < min_confidence  # type: ignore[operator]
            ):
                continue
            keep.append(row)
        return keep

    # ----- export -----------------------------------------------------------------------------

    def export_sources(self, fmt: str, removed: bool = False) -> tuple[bytes, str, str]:
        client = self._client()
        sources = client.sources.list(include_removed=removed)
        return self._export(lambda path: client.sources.export(sources, path, fmt), "sources", fmt)

    def export_files(self, source_id: int, fmt: str, **filters: Any) -> tuple[bytes, str, str]:
        """The files of a source that match the filters (the ones the screen shows), as a file."""
        client = self._client()
        _, items, rows = self._cache_entry(source_id)
        wanted = {
            id(r)
            for r in self._filter(
                rows,
                filters.get("q", ""),
                filters.get("status"),
                filters.get("file_type"),
                filters.get("band"),
                filters.get("min_confidence"),
            )
        }
        chosen = [item for item, row in zip(items, rows, strict=True) if id(row) in wanted]
        source = client.sources.get(source_id)
        return self._export(
            lambda path: client.sources.export_files(source, chosen, path, fmt),
            f"files-of-{source_id}",
            fmt,
        )

    def _cache_entry(self, source_id: int) -> tuple[float, list[Any], list[dict[str, object]]]:
        self._scan(source_id, False)
        with self._lock:
            return self._cache[source_id]

    @staticmethod
    def _export(write: Callable[[Path], Any], name: str, fmt: str) -> tuple[bytes, str, str]:
        if fmt not in _MIMES:
            raise ValueError("format is json or html.")
        with tempfile.TemporaryDirectory(prefix="vethuq-export-") as folder:
            target = Path(folder) / f"{name}.{fmt}"
            write(target)
            return target.read_bytes(), target.name, _MIMES[fmt]
