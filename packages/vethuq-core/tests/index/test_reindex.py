from pathlib import Path

import pytest
from vethuq_core.index import (
    AlreadyRunningError,
    AmbiguousFileError,
    FileNotTrackedError,
    IndexRunner,
    Reindex,
)
from vethuq_core.index import runner as index_runner
from vethuq_core.sources import Sources


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vethuq.db"


@pytest.fixture
def started(monkeypatch):
    """Capture the worker argv instead of launching a real process."""
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        return _FakeProcess(4321)

    monkeypatch.setattr(index_runner.subprocess, "Popen", fake_popen)
    return captured


def _track(conn, source_id, path, status="indexed"):
    doc_id = conn.execute("INSERT INTO documents (created_at) VALUES ('2026-01-01')").lastrowid
    row_id = conn.execute(
        "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
        "VALUES (?, ?, ?, 'pdf', ?)",
        (source_id, doc_id, str(path), status),
    ).lastrowid
    conn.commit()
    return row_id, doc_id


def _status(conn, row_id):
    return conn.execute("SELECT status FROM document_index WHERE id = ?", (row_id,)).fetchone()[0]


@pytest.fixture
def source(storage, conn, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    conn.commit()
    return Sources.add(storage, folder)


class TestReindexSource:
    def test_resets_indexed_and_failed_rows_but_keeps_documents(
        self, db_path, conn, source, started
    ):
        ok, ok_doc = _track(conn, source.id, Path(source.path) / "a.pdf", "indexed")
        bad, _ = _track(conn, source.id, Path(source.path) / "b.pdf", "error")
        gone, _ = _track(conn, source.id, Path(source.path) / "c.pdf", "removed")

        pid = Reindex.start_source(source.id, db_path=db_path)

        assert pid == 4321
        assert started["argv"][-1] == "run"
        assert (_status(conn, ok), _status(conn, bad), _status(conn, gone)) == (
            "pending",
            "pending",
            "removed",
        )
        assert (
            conn.execute("SELECT document_id FROM document_index WHERE id = ?", (ok,)).fetchone()[0]
            == ok_doc
        )

    def test_refuses_when_a_run_is_active(self, db_path, conn, source, monkeypatch):
        row, _ = _track(conn, source.id, Path(source.path) / "a.pdf")
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: True)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "111")

        with pytest.raises(AlreadyRunningError):
            Reindex.start_source(source.id, db_path=db_path)

        assert _status(conn, row) == "indexed"


class TestReindexFile:
    def test_resets_only_the_chosen_file_by_path(self, db_path, conn, source, started):
        target, _ = _track(conn, source.id, Path(source.path) / "a.pdf")
        other, _ = _track(conn, source.id, Path(source.path) / "b.pdf")

        Reindex.start_file(Path(source.path) / "a.pdf", db_path=db_path)

        assert _status(conn, target) == "pending"
        assert _status(conn, other) == "indexed"

    def test_accepts_a_document_id(self, db_path, conn, source, started):
        target, _ = _track(conn, source.id, Path(source.path) / "a.pdf")

        Reindex.start_file(str(target), db_path=db_path)

        assert _status(conn, target) == "pending"

    def test_untracked_file_is_rejected(self, db_path, conn, source, started):
        with pytest.raises(FileNotTrackedError):
            Reindex.start_file(Path(source.path) / "missing.pdf", db_path=db_path)

    def test_file_under_two_sources_needs_source_option(
        self, db_path, storage, conn, source, started
    ):
        inner = Path(source.path) / "inner"
        inner.mkdir()
        inner_source = Sources.add(storage, inner)
        file = inner / "a.pdf"
        row, _ = _track(conn, inner_source.id, file)

        with pytest.raises(AmbiguousFileError, match="--source"):
            Reindex.start_file(file, db_path=db_path)

        Reindex.start_file(file, source=inner_source.id, db_path=db_path)
        assert _status(conn, row) == "pending"

    def test_source_option_must_own_the_file(self, db_path, storage, conn, source, started):
        inner = Path(source.path) / "inner"
        inner.mkdir()
        inner_source = Sources.add(storage, inner)
        row, _ = _track(conn, inner_source.id, inner / "a.pdf")

        with pytest.raises(FileNotTrackedError, match="not"):
            Reindex.start_file(inner / "a.pdf", source=source.id, db_path=db_path)

        assert _status(conn, row) == "indexed"
