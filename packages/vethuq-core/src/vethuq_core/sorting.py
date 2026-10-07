"""Ordering for the lists the commands print: search results, index jobs and runs, per-file index
status, and the installed file types, search engines and OCR models.

Every list takes the same two choices: an `Order` (`asc` or `desc`) and a column to sort `By`.
A list with a natural order of its own (search results come best first) is left as it is unless
the caller asks for one; an unset `by` with an `order` sorts by the list's first column.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any


class Sorting:
    class Order(StrEnum):
        ASC = "asc"
        DESC = "desc"

    class SearchBy(StrEnum):
        FILE = "file"
        PAGE = "page"
        SCORE = "score"
        ENGINE = "engine"

    class JobBy(StrEnum):
        ID = "id"
        STATUS = "status"
        KIND = "kind"
        TARGET = "target"
        QUEUED = "queued"

    class RunBy(StrEnum):
        ID = "id"
        STARTED = "started"
        MODE = "mode"
        TARGET = "target"
        STATUS = "status"

    class FileBy(StrEnum):
        FILE = "file"
        STATUS = "status"
        CONFIDENCE = "confidence"
        DURATION = "duration"

    class CatalogBy(StrEnum):
        NAME = "name"
        PACKAGE = "package"
        STATUS = "status"

    class ModelBy(StrEnum):
        MODEL = "model"
        SIZE = "size"
        STATUS = "status"

    @staticmethod
    def _key(value: Any) -> tuple[bool, Any]:
        """Text sorts without regard to case; a missing value (None) sorts after the rest."""
        if isinstance(value, str):
            value = value.casefold()
        return (value is None, 0 if value is None else value)

    @staticmethod
    def apply(
        items: Iterable[Any],
        keys: dict[Any, Callable[[Any], Any]],
        by: Any | None,
        order: Sorting.Order | None,
    ) -> list[Any]:
        """`items` sorted by the key `by` names in `keys` (the first key when only `order` is
        given), or as they came when neither is. The sort is stable, so ties keep their order.
        Missing values come last whichever way it runs."""
        listed = list(items)
        if by is None and order is None:
            return listed
        key = keys[by] if by is not None else next(iter(keys.values()))
        if order is Sorting.Order.DESC:
            present = [i for i in listed if key(i) is not None]
            missing = [i for i in listed if key(i) is None]
            present.sort(key=lambda i: Sorting._key(key(i)), reverse=True)
            return present + missing
        return sorted(listed, key=lambda i: Sorting._key(key(i)))

    @staticmethod
    def search_results(
        results: Iterable[Any], by: Sorting.SearchBy | None, order: Sorting.Order | None
    ) -> list[Any]:
        """Search matches or pages. `file` keeps a file's pages in page order."""
        by_file = lambda r: (r.file_path.casefold(), r.page_number or 0)  # noqa: E731
        keys = {
            Sorting.SearchBy.FILE: by_file,
            Sorting.SearchBy.PAGE: lambda r: r.page_number,
            Sorting.SearchBy.SCORE: lambda r: r.score,
            Sorting.SearchBy.ENGINE: lambda r: r.engine,
        }
        return Sorting.apply(results, keys, by, order)

    @staticmethod
    def jobs(
        jobs: Iterable[Any], by: Sorting.JobBy | None, order: Sorting.Order | None
    ) -> list[Any]:
        keys = {
            Sorting.JobBy.ID: lambda j: j.id,
            Sorting.JobBy.STATUS: lambda j: j.status,
            Sorting.JobBy.KIND: lambda j: j.mode,
            Sorting.JobBy.TARGET: lambda j: j.target or "all sources",
            Sorting.JobBy.QUEUED: lambda j: j.requested_at,
        }
        return Sorting.apply(jobs, keys, by, order)

    @staticmethod
    def runs(
        runs: Iterable[Any], by: Sorting.RunBy | None, order: Sorting.Order | None
    ) -> list[Any]:
        keys = {
            Sorting.RunBy.ID: lambda r: r.id,
            Sorting.RunBy.STARTED: lambda r: r.started_at,
            Sorting.RunBy.MODE: lambda r: r.mode,
            Sorting.RunBy.TARGET: lambda r: r.target or "all sources",
            Sorting.RunBy.STATUS: lambda r: r.status,
        }
        return Sorting.apply(runs, keys, by, order)

    @staticmethod
    def files(
        files: Iterable[Any], by: Sorting.FileBy | None, order: Sorting.Order | None
    ) -> list[Any]:
        """Per-file index results (`vethuq index status SOURCE`)."""
        keys = {
            Sorting.FileBy.FILE: lambda f: f.file_path,
            Sorting.FileBy.STATUS: lambda f: f.status,
            Sorting.FileBy.CONFIDENCE: lambda f: f.confidence,
            Sorting.FileBy.DURATION: lambda f: f.duration,
        }
        return Sorting.apply(files, keys, by, order)

    @staticmethod
    def catalog(
        entries: Iterable[Any],
        status: Callable[[Any], str],
        by: Sorting.CatalogBy | None,
        order: Sorting.Order | None,
    ) -> list[Any]:
        """File types or search engines (anything with `label`, `extra`); `status` names how
        installed one is."""
        keys = {
            Sorting.CatalogBy.NAME: lambda e: e.label,
            Sorting.CatalogBy.PACKAGE: lambda e: e.extra,
            Sorting.CatalogBy.STATUS: status,
        }
        return Sorting.apply(entries, keys, by, order)

    @staticmethod
    def models(
        models: Iterable[Any], by: Sorting.ModelBy | None, order: Sorting.Order | None
    ) -> list[Any]:
        keys = {
            Sorting.ModelBy.MODEL: lambda m: m.name,
            Sorting.ModelBy.SIZE: lambda m: m.size_bytes,
            Sorting.ModelBy.STATUS: lambda m: m.present,
        }
        return Sorting.apply(models, keys, by, order)
