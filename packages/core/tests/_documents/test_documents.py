from __future__ import annotations

import pytest
from sqlalchemy import func, select

from vethuq._db import _Database, _Document, _DocumentIndex, _Source
from vethuq._documents import _Documents, _FileTypes
from vethuq._sources import _Sources
from vethuq.enums import FileStatus, SourceStatus


@pytest.fixture
def database(tmp_path):
    database = _Database(tmp_path / "db" / "vethuq.db")
    yield database
    database.dispose()


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    return root


@pytest.fixture
def session(database):
    with database.session() as session:
        yield session


@pytest.fixture
def source(session, folder):
    return _Sources.create(session, folder)


def add(session, source, name, size=1, modified="2026-01-01T00:00:00+00:00"):
    return _Documents.register(session, source, f"{source.path}/{name}", size, modified)


class TestFileTypes:
    @pytest.mark.parametrize("name", ["a.pdf", "A.PDF", "dir/x.Pdf"])
    def test_pdf_is_supported(self, name):
        assert _FileTypes.is_supported(name)

    @pytest.mark.parametrize("name", ["a.txt", "a.png", "pdf", "a.pdf.bak", ""])
    def test_everything_else_is_not(self, name):
        assert not _FileTypes.is_supported(name)


class TestRegister:
    def test_a_new_file_is_pending(self, session, source):
        row = add(session, source, "a.pdf", size=5)
        assert row.status is FileStatus.PENDING
        assert (row.size_bytes, row.document_id, row.sha256) == (5, None, None)
        assert row.discovered_at

    def test_registering_twice_is_harmless(self, session, source):
        add(session, source, "a.pdf")
        add(session, source, "a.pdf")
        assert session.scalar(select(func.count()).select_from(_DocumentIndex)) == 1

    def test_a_changed_indexed_file_becomes_modified(self, session, source):
        row = add(session, source, "a.pdf")
        _Documents.finish(session, row, "h1")
        add(session, source, "a.pdf", size=99)
        assert row.status is FileStatus.MODIFIED
        assert row.size_bytes == 99

    def test_an_unchanged_indexed_file_stays_indexed(self, session, source):
        row = add(session, source, "a.pdf")
        _Documents.finish(session, row, "h1")
        add(session, source, "a.pdf")
        assert row.status is FileStatus.INDEXED

    def test_a_changed_pending_file_stays_pending(self, session, source):
        row = add(session, source, "a.pdf")
        add(session, source, "a.pdf", size=7)
        assert row.status is FileStatus.PENDING and row.size_bytes == 7

    def test_a_removed_file_that_is_back_becomes_pending(self, session, source):
        row = add(session, source, "a.pdf")
        _Documents.mark_removed(session, row)
        add(session, source, "a.pdf")
        assert row.status is FileStatus.PENDING and row.removed_at is None

    def test_a_path_cannot_belong_to_two_sources(self, session, source, tmp_path):
        other = _Source(
            path=str(tmp_path / "elsewhere"),
            source_type=source.source_type,
            added_at="2026-01-01",
        )
        session.add(other)
        session.flush()
        row = add(session, source, "a.pdf")
        with pytest.raises(ValueError, match="already belongs"):
            _Documents.register(session, other, row.file_path, 1, "x")


class TestChanges:
    def test_start_finish_fail_and_remove(self, session, source):
        row = add(session, source, "a.pdf")
        _Documents.start(session, row)
        assert row.status is FileStatus.PROCESSING and row.started_at
        _Documents.fail(session, row, "boom")
        assert (row.status, row.error_message, row.retry_count) == (FileStatus.ERROR, "boom", 1)
        _Documents.start(session, row)
        assert row.error_message is None and row.completed_at is None
        _Documents.finish(session, row, "h1")
        assert row.status is FileStatus.INDEXED and row.indexed_at and row.sha256 == "h1"
        _Documents.mark_removed(session, row)
        assert row.status is FileStatus.REMOVED and row.removed_at


class TestDuplicates:
    def test_same_content_shares_one_document(self, session, source):
        first, second = add(session, source, "a.pdf"), add(session, source, "b.pdf")
        _Documents.finish(session, first, "same")
        _Documents.finish(session, second, "same")
        assert first.document_id == second.document_id
        assert session.scalar(select(func.count()).select_from(_Document)) == 1

    def test_the_original_is_the_earliest_row(self, session, source):
        first, second = add(session, source, "a.pdf"), add(session, source, "b.pdf")
        _Documents.finish(session, second, "same")  # finished first, but registered later
        _Documents.finish(session, first, "same")
        originals = _Documents.original_paths(session, {first.document_id})
        assert originals == {first.document_id: (first.id, first.file_path)}

    def test_no_documents_no_originals(self, session):
        assert _Documents.original_paths(session, set()) == {}


class TestOverall:
    @pytest.mark.parametrize(
        ("counts", "expected"),
        [
            ({}, (SourceStatus.PENDING, 0, 0)),
            ({FileStatus.UNSUPPORTED: 3, FileStatus.REMOVED: 2}, (SourceStatus.PENDING, 0, 0)),
            ({FileStatus.PENDING: 4}, (SourceStatus.PENDING, 4, 0)),
            ({FileStatus.PROCESSING: 1, FileStatus.PENDING: 3}, (SourceStatus.IN_PROGRESS, 4, 0)),
            ({FileStatus.INDEXED: 1, FileStatus.PENDING: 3}, (SourceStatus.IN_PROGRESS, 4, 1)),
            ({FileStatus.ERROR: 1, FileStatus.PENDING: 1}, (SourceStatus.IN_PROGRESS, 2, 1)),
            ({FileStatus.INDEXED: 2, FileStatus.MODIFIED: 1}, (SourceStatus.IN_PROGRESS, 3, 2)),
            ({FileStatus.INDEXED: 3}, (SourceStatus.COMPLETED, 3, 3)),
            ({FileStatus.INDEXED: 2, FileStatus.ERROR: 1}, (SourceStatus.ERROR, 3, 3)),
            ({FileStatus.INDEXED: 2, FileStatus.REMOVED: 5}, (SourceStatus.COMPLETED, 2, 2)),
        ],
    )
    def test_overall(self, counts, expected):
        assert _Documents.overall(counts) == expected

    def test_the_source_follows_its_files(self, session, source):
        a, b = add(session, source, "a.pdf"), add(session, source, "b.pdf")
        assert (source.status, source.files_processed, source.files_total) == (
            SourceStatus.PENDING,
            0,
            2,
        )
        _Documents.finish(session, a, "h1")
        assert (source.status, source.files_processed) == (SourceStatus.IN_PROGRESS, 1)
        _Documents.fail(session, b, "x")
        assert (source.status, source.files_processed) == (SourceStatus.ERROR, 2)
        _Documents.finish(session, b, "h2")
        assert source.status is SourceStatus.COMPLETED

    def test_a_removed_source_stays_removed(self, session, source):
        row = add(session, source, "a.pdf")
        _Sources.remove(session, source.id)
        _Documents.finish(session, row, "h")
        assert source.status is SourceStatus.REMOVED
        assert source.files_processed == 1

    def test_refreshing_an_unknown_source_is_a_no_op(self, session):
        _Documents.refresh_source(session, 999)


class TestSourceLifecycle:
    def test_reactivating_keeps_known_files_and_recomputes_status(self, session, source, folder):
        row = add(session, source, "a.pdf")
        _Documents.finish(session, row, "h")
        _Sources.remove(session, source.id)
        again = _Sources.create(session, folder)
        assert again.id == source.id
        assert (again.status, again.files_processed, again.files_total) == (
            SourceStatus.COMPLETED,
            1,
            1,
        )

    def test_purging_deletes_files_and_orphaned_documents(self, session, source, tmp_path):
        row = add(session, source, "a.pdf")
        _Documents.finish(session, row, "h")
        _Sources.remove(session, source.id)
        _Sources.purge(session, source.id)
        assert session.scalar(select(func.count()).select_from(_DocumentIndex)) == 0
        assert session.scalar(select(func.count()).select_from(_Document)) == 0

    def test_a_document_shared_with_another_source_survives_a_purge(self, session, tmp_path):
        one, two = tmp_path / "one", tmp_path / "two"
        one.mkdir()
        two.mkdir()
        first, second = _Sources.create(session, one), _Sources.create(session, two)
        a, b = add(session, first, "a.pdf"), add(session, second, "b.pdf")
        _Documents.finish(session, a, "same")
        _Documents.finish(session, b, "same")
        _Sources.remove(session, first.id)
        _Sources.purge(session, first.id)
        assert session.scalar(select(func.count()).select_from(_Document)) == 1
        assert session.get(_Source, second.id) is not None

    def test_retention_purge_cleans_up_too(self, session, source):
        row = add(session, source, "a.pdf")
        _Documents.finish(session, row, "h")
        _Sources.remove(session, source.id)
        _Sources.purge_expired(session, 0)
        assert session.scalar(select(func.count()).select_from(_DocumentIndex)) == 0
        assert session.scalar(select(func.count()).select_from(_Document)) == 0
