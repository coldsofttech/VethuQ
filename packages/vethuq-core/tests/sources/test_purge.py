import logging
import sqlite3
from datetime import UTC, datetime

import pytest
from vethuq_core.sources import SourceNotFoundError, SourceNotRemovedError, Sources
from vethuq_core.storage import Storage


def _insert_file(conn: sqlite3.Connection, source_id: int, path: str, status: str) -> int:
    document_id = conn.execute(
        "INSERT INTO documents (created_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
    ).lastrowid
    row_id = conn.execute(
        "INSERT INTO document_index (document_id, source_id, file_path, file_type, status) "
        "VALUES (?, ?, ?, 'pdf', ?)",
        (document_id, source_id, path, status),
    ).lastrowid
    assert row_id is not None
    return row_id


class TestPurge:
    def test_purges_a_removed_source_inside_retention_and_logs_it(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path, caplog
    ):
        folder = tmp_path / "docs"
        folder.mkdir()
        source = Sources.add(storage, folder)
        _insert_file(conn, source.id, str(folder / "a.pdf"), "indexed")
        Sources.remove(storage, source.id)

        with caplog.at_level(logging.INFO, logger="vethuq.database"):
            result = Sources.purge(storage, source.id)

        assert (result.kind, result.path) == ("folder", source.path)
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM document_index").fetchone()[0] == 0
        assert "Cleanup (manual): purged source" in caplog.text
        assert "1 indexed file record(s)" in caplog.text

    def test_active_source_is_refused_and_kept(self, storage: Storage, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        source = Sources.add(storage, folder)

        with pytest.raises(SourceNotRemovedError):
            Sources.purge(storage, source.id)

        assert Sources.get(storage, source.id).id == source.id

    def test_purges_only_the_named_removed_file(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path, caplog
    ):
        folder = tmp_path / "docs"
        folder.mkdir()
        source = Sources.add(storage, folder)
        gone = str((folder / "gone.pdf").resolve())
        _insert_file(conn, source.id, gone, "removed")
        _insert_file(conn, source.id, str((folder / "keep.pdf").resolve()), "indexed")

        with caplog.at_level(logging.INFO, logger="vethuq.database"):
            result = Sources.purge(storage, gone)

        assert (result.kind, result.path) == ("file", gone)
        remaining = [r["file_path"] for r in conn.execute("SELECT file_path FROM document_index")]
        assert remaining == [str((folder / "keep.pdf").resolve())]
        assert f"path={gone}" in caplog.text

    def test_a_file_that_is_not_removed_is_refused(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path
    ):
        folder = tmp_path / "docs"
        folder.mkdir()
        source = Sources.add(storage, folder)
        active = str((folder / "a.pdf").resolve())
        _insert_file(conn, source.id, active, "indexed")

        with pytest.raises(SourceNotRemovedError):
            Sources.purge(storage, active)

    def test_unknown_target_is_not_found(self, storage: Storage, tmp_path):
        with pytest.raises(SourceNotFoundError):
            Sources.purge(storage, tmp_path / "nope")
        with pytest.raises(SourceNotFoundError):
            Sources.purge(storage, 999)

    def test_retention_purge_is_logged_as_such(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path, caplog
    ):
        folder = tmp_path / "docs"
        folder.mkdir()
        source = Sources.add(storage, folder)
        Sources.remove(storage, source.id)

        with caplog.at_level(logging.INFO, logger="vethuq.database"):
            assert Sources.purge_expired_sources(storage, retention_minutes=-1) == 1

        assert "Cleanup (retention): purged source" in caplog.text
