"""Ordering of sources and of the files under a source."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from vethuq_core.sources.source import Source, SourceFile


class SourceSort:
    """Sort keys and orders for listing sources and their files."""

    class Order(StrEnum):
        ASC = "asc"
        DESC = "desc"

    class By(StrEnum):
        FILENAME = "filename"
        ID = "id"
        STATUS = "status"

    @staticmethod
    def file_name(source: Source, file: SourceFile) -> str:
        """The file's path relative to a folder source (its name, for a file source)."""
        if source.source_type == "folder":
            try:
                return Path(file.file_path).relative_to(source.path).as_posix()
            except ValueError:
                pass
        return Path(file.file_path).name

    @staticmethod
    def files(
        source: Source, files: list[SourceFile], order: SourceSort.Order, by: SourceSort.By
    ) -> list[SourceFile]:
        keys = {
            SourceSort.By.FILENAME: lambda f: SourceSort.file_name(source, f).casefold(),
            SourceSort.By.ID: lambda f: f.id,
            SourceSort.By.STATUS: lambda f: f.status,
        }
        return sorted(files, key=keys[by], reverse=order is SourceSort.Order.DESC)

    @staticmethod
    def sources(sources: list[Source], order: SourceSort.Order, by: SourceSort.By) -> list[Source]:
        """For sources, `filename` sorts by the registered path."""
        keys = {
            SourceSort.By.FILENAME: lambda s: s.path.casefold(),
            SourceSort.By.ID: lambda s: s.id,
            SourceSort.By.STATUS: lambda s: s.status,
        }
        return sorted(sources, key=keys[by], reverse=order is SourceSort.Order.DESC)
