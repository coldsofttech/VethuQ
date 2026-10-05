"""Manual re-indexing of a whole source or a single file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from vethuq_core.index.runner import AlreadyRunningError, IndexRunner, IndexRunnerError
from vethuq_core.logs import Logs
from vethuq_core.sources import Source, Sources
from vethuq_core.storage import Storage, default_db_path, open_storage

if TYPE_CHECKING:
    from vethuq_core.index.submit import IndexSubmission


class FileNotTrackedError(IndexRunnerError):
    """The chosen file isn't tracked under any registered source."""


class AmbiguousFileError(IndexRunnerError):
    """The chosen file sits under more than one registered source."""


class Reindex:
    """Send indexed files back through OCR, updating their existing documents in place.

    Files keep their logical documents, so re-indexing never creates duplicates.
    The files are reset to pending and then a normal background run picks them
    up, so progress, pause and stop all work as usual.
    """

    @staticmethod
    def start_source(
        target: str | Path | int,
        *,
        force: bool = False,
        db_path: Path | None = None,
        on_recovery: Callable[[list[str]], None] | None = None,
        languages: str | None = None,
    ) -> int:
        """Re-index every file under a source (id or path). Returns the worker's pid.

        `languages` reads the files in those languages this time (see `IndexRunner.start_run`);
        to make the choice lasting, set it on the source (`Sources.set_languages`).
        """
        db_path = db_path or default_db_path()
        source = Reindex._prepare_source(target, db_path)
        return IndexRunner.start_run(
            str(source.id),
            force=force,
            db_path=db_path,
            on_recovery=on_recovery,
            languages=languages,
        )

    @staticmethod
    def submit_source(
        target: str | Path | int,
        *,
        force: bool = False,
        via: str = "auto",
        db_path: Path | None = None,
        on_recovery: Callable[[list[str]], None] | None = None,
        languages: str | None = None,
    ) -> IndexSubmission:
        """Like `start_source`, but queued for the background service when this build has one."""
        db_path = db_path or default_db_path()
        source = Reindex._prepare_source(target, db_path)
        from vethuq_core.index.submit import Indexing

        return Indexing.submit(
            str(source.id),
            languages=languages,
            force=force,
            via=via,
            db_path=db_path,
            on_recovery=on_recovery,
        )

    @staticmethod
    def _prepare_source(target: str | Path | int, db_path: Path) -> Source:
        """Reset every file under the source to pending, ready for a run to pick up."""
        Reindex._refuse_if_running(db_path)
        storage = open_storage(db_path)
        try:
            source = Sources.get(storage, Sources.coerce(target))
            with storage.transaction():
                storage.reset_document_index_for_reindex(source.id)
        finally:
            storage.close()
        return source

    @staticmethod
    def start_file(
        file: str | Path | int,
        *,
        source: str | Path | int | None = None,
        force: bool = False,
        db_path: Path | None = None,
        on_recovery: Callable[[list[str]], None] | None = None,
        languages: str | None = None,
    ) -> int:
        """Re-index one file, by document id or path. Returns the worker's pid.

        `languages` reads the file in those languages this time (see `IndexRunner.start_run`).

        When a path sits under more than one registered source, `source` (id or
        path) must say which one - otherwise `AmbiguousFileError` is raised.
        """
        db_path = db_path or default_db_path()
        owner = Reindex._prepare_file(file, source, db_path)
        return IndexRunner.start_run(
            str(owner.id),
            force=force,
            db_path=db_path,
            on_recovery=on_recovery,
            languages=languages,
        )

    @staticmethod
    def submit_file(
        file: str | Path | int,
        *,
        source: str | Path | int | None = None,
        force: bool = False,
        via: str = "auto",
        db_path: Path | None = None,
        on_recovery: Callable[[list[str]], None] | None = None,
        languages: str | None = None,
    ) -> IndexSubmission:
        """Like `start_file`, but queued for the background service when this build has one."""
        db_path = db_path or default_db_path()
        owner = Reindex._prepare_file(file, source, db_path)
        from vethuq_core.index.submit import Indexing

        return Indexing.submit(
            str(owner.id),
            languages=languages,
            force=force,
            via=via,
            db_path=db_path,
            on_recovery=on_recovery,
        )

    @staticmethod
    def _prepare_file(
        file: str | Path | int, source: str | Path | int | None, db_path: Path
    ) -> Source:
        """Reset one file to pending; returns the source that owns it."""
        Reindex._refuse_if_running(db_path)
        storage = open_storage(db_path)
        try:
            row_source, file_path = Reindex._resolve_file(storage, file, source)
            with storage.transaction():
                storage.reset_document_index_for_reindex(row_source.id, file_path)
        finally:
            storage.close()
        return row_source

    @staticmethod
    def _refuse_if_running(db_path: Path) -> None:
        Logs.setup("index", db_path)
        running, pid = IndexRunner.is_running(db_path)
        if running:
            raise AlreadyRunningError(f"An index run is already in progress (pid {pid}).")

    @staticmethod
    def _resolve_file(
        storage: Storage, file: str | Path | int, source: str | Path | int | None
    ) -> tuple[Source, str]:
        file = Sources.coerce(file) if isinstance(file, str) else file
        if isinstance(file, int):
            row = storage.find_document_index_row_for_reindex(row_id=file)
            if row is None:
                raise FileNotTrackedError(f"No tracked file has id {file}.")
        else:
            path = str(Path(file).expanduser().resolve())
            row = storage.find_document_index_row_for_reindex(file_path=path)
            if row is None:
                raise FileNotTrackedError(
                    f"{path} isn't tracked under any source. "
                    "Register its folder with 'vethuq source add <path>' first."
                )
            Reindex._check_ambiguity(storage, Path(path), source)

        owner = Sources.get(storage, row["source_id"])
        if source is not None:
            chosen = Sources.get(storage, Sources.coerce(source))
            if chosen.id != owner.id:
                raise FileNotTrackedError(
                    f"{row['file_path']} is tracked under source {owner.id}, not {chosen.id}."
                )
        return owner, row["file_path"]

    @staticmethod
    def _check_ambiguity(storage: Storage, path: Path, source: str | Path | int | None) -> None:
        if source is not None:
            return
        covering = [
            s
            for s in Sources.list_all(storage)
            if s.status != "removed" and (path == Path(s.path) or path.is_relative_to(s.path))
        ]
        if len(covering) > 1:
            listing = ", ".join(f"{s.id} ({s.path})" for s in covering)
            raise AmbiguousFileError(
                f"{path} is under more than one source: {listing}. "
                "Pass --source <id or path> to choose one."
            )
