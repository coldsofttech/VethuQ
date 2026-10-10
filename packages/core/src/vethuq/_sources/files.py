"""Finding the files on disk that belong to a source."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from vethuq._errors import _SourcePathError


@dataclass(frozen=True)
class _FileEntry:
    path: str
    relative_path: str
    name: str
    size_bytes: int
    modified_at: str


class _Files:
    @staticmethod
    def entry(path: Path, root: Path) -> _FileEntry | None:
        """The details of one file, or None if it can't be read (it vanished meanwhile)."""
        try:
            stat = path.stat()
        except OSError:
            return None
        if path == root:
            relative = path.name
        else:
            relative = path.relative_to(root).as_posix()
        return _FileEntry(
            path=str(path),
            relative_path=relative,
            name=path.name,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        )

    @staticmethod
    def list(source_path: str | Path) -> list[_FileEntry]:
        """The files of a source, sorted by their path relative to it.

        A folder gives every file under it, however deep; a file gives itself. Folders reached
        through a link are not followed, so a link back up the tree can't cause a loop, and
        folders that can't be read are skipped. Raises `SourcePathError` if the path is no
        longer there.
        """
        root = Path(source_path)
        if root.is_file():
            entry = _Files.entry(root, root)
            return [entry] if entry is not None else []
        if not root.is_dir():
            raise _SourcePathError(
                f"The source's path no longer exists: {root}",
                "Restore it, or remove the source.",
            )
        entries = []
        for directory, _folders, names in os.walk(root, followlinks=False):
            for name in names:
                path = Path(directory) / name
                if path.is_file():  # skips broken links and anything that isn't a regular file
                    entry = _Files.entry(path, root)
                    if entry is not None:
                        entries.append(entry)
        entries.sort(key=lambda e: (e.relative_path.casefold(), e.relative_path))
        return entries
