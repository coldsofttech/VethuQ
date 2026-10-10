from __future__ import annotations

import json
from pathlib import Path

import pytest

import vethuq
from vethuq import errors
from vethuq._db import _Source
from vethuq._documents import _Documents
from vethuq._sources import _Files
from vethuq.sources import FileIndex, FileStatus, SourceStatus


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.pdf").write_bytes(b"a")
    (folder / "b.pdf").write_bytes(b"bb")
    (folder / "sub" / "c.pdf").write_bytes(b"ccc")
    (folder / "notes.txt").write_text("text")
    return folder


class Index:
    """Writes document-index rows the way the indexer will, for tests."""

    def __init__(self, client) -> None:
        self.client = client

    def row(self, source_id, path, action=None, *, sha256="h", message="boom"):
        entry = _Files.entry(Path(path), Path(path).parent)
        with self.client._db().session() as session:
            source = session.get(_Source, source_id)
            row = _Documents.register(
                session, source, entry.path, entry.size_bytes, entry.modified_at
            )
            if action == "start":
                _Documents.start(session, row)
            elif action == "finish":
                _Documents.finish(session, row, sha256)
            elif action == "fail":
                _Documents.fail(session, row, message)
            elif action == "remove":
                _Documents.mark_removed(session, row)


def listing(client, source, **kwargs):
    return {f.relative_path: f for f in client.sources.list_files(source.id, **kwargs)}


class TestDetailedListing:
    def test_a_plain_listing_has_no_index(self, client, root):
        source = client.sources.create(root)
        assert all(f.index is None for f in client.sources.list_files(source.id))

    def test_nothing_indexed_yet(self, client, root):
        source = client.sources.create(root)
        files = listing(client, source, detailed=True)
        assert {k: v.index.status for k, v in files.items()} == {
            "a.pdf": FileStatus.PENDING,
            "b.pdf": FileStatus.PENDING,
            "notes.txt": FileStatus.UNSUPPORTED,
            "sub/c.pdf": FileStatus.PENDING,
        }
        assert files["a.pdf"].index == FileIndex(FileStatus.PENDING)

    def test_each_state_is_reported(self, client, root):
        source = client.sources.create(root)
        index = Index(client)
        index.row(source.id, root / "a.pdf", "finish", sha256="s1")
        index.row(source.id, root / "b.pdf", "fail", message="unreadable")
        index.row(source.id, root / "sub" / "c.pdf", "start")
        files = listing(client, source, detailed=True)
        assert files["a.pdf"].index.status is FileStatus.INDEXED
        assert files["a.pdf"].index.sha256 == "s1" and files["a.pdf"].index.indexed_at
        assert files["b.pdf"].index.status is FileStatus.ERROR
        assert files["b.pdf"].index.error == "unreadable" and files["b.pdf"].index.retry_count == 1
        assert files["sub/c.pdf"].index.status is FileStatus.PROCESSING

    def test_a_file_changed_since_indexing_is_modified(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "a.pdf", "finish")
        (root / "a.pdf").write_bytes(b"changed content")
        assert listing(client, source, detailed=True)["a.pdf"].index.status is FileStatus.MODIFIED

    def test_a_file_that_is_gone_is_listed_as_removed(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "sub" / "c.pdf", "finish")
        (root / "sub" / "c.pdf").unlink()
        gone = listing(client, source, detailed=True)["sub/c.pdf"]
        assert gone.index.status is FileStatus.REMOVED and gone.index.on_disk is False
        assert gone.name == "c.pdf" and gone.size_bytes == 3
        assert "sub/c.pdf" not in listing(client, source)  # the plain listing is disk only

    def test_a_removed_file_that_is_back_is_pending(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "a.pdf", "remove")
        assert listing(client, source, detailed=True)["a.pdf"].index.status is FileStatus.PENDING

    def test_duplicates_point_at_the_original(self, client, root):
        source = client.sources.create(root)
        index = Index(client)
        index.row(source.id, root / "b.pdf", "finish", sha256="same")
        index.row(source.id, root / "a.pdf", "finish", sha256="same")
        files = listing(client, source, detailed=True)
        assert files["b.pdf"].index.duplicate_of is None
        assert files["a.pdf"].index.duplicate_of == str(root / "b.pdf")

    def test_a_single_file_source(self, client, root):
        source = client.sources.create(root / "a.pdf")
        Index(client).row(source.id, root / "a.pdf", "finish")
        (only,) = client.sources.list_files(source.id, detailed=True)
        assert only.relative_path == "a.pdf" and only.index.status is FileStatus.INDEXED
        (root / "a.pdf").unlink()
        with pytest.raises(errors.SourcePathError):
            client.sources.list_files(source.id, detailed=True)

    def test_filtering_by_status(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "a.pdf", "finish")
        done = client.sources.list_files(source.id, detailed=True, status=FileStatus.INDEXED)
        assert [f.relative_path for f in done] == ["a.pdf"]
        pending = client.sources.list_files(source.id, detailed=True, status="pending")
        assert [f.relative_path for f in pending] == ["b.pdf", "sub/c.pdf"]

    def test_the_status_filter_needs_detailed(self, client, root):
        source = client.sources.create(root)
        with pytest.raises(ValueError, match="detailed"):
            client.sources.list_files(source.id, status="pending")

    def test_a_bad_status_is_refused(self, client, root):
        source = client.sources.create(root)
        with pytest.raises(ValueError, match="status must be one of"):
            client.sources.list_files(source.id, detailed=True, status="nope")

    def test_reading_changes_nothing(self, client, root):
        source = client.sources.create(root)
        listing(client, source, detailed=True)
        assert client.sources.get(source.id).files_total == 0

    def test_serialising(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "a.pdf", "finish")
        plain = listing(client, source)["a.pdf"].to_dict()
        detailed = listing(client, source, detailed=True)["a.pdf"]
        assert "index" not in plain
        assert detailed.to_dict()["index"]["status"] == "indexed"
        assert json.loads(detailed.to_json())["index"]["on_disk"] is True
        assert json.loads(detailed.index.to_json(indent=2))["retry_count"] == 0


class TestSourceProgress:
    def test_a_new_source_has_no_progress(self, client, root):
        source = client.sources.create(root)
        assert source.status is SourceStatus.PENDING
        assert (source.files_processed, source.files_total) == (0, 0)
        assert source.progress == "0 of 0 files processed"

    def test_the_source_follows_its_files(self, client, root):
        source = client.sources.create(root)
        index = Index(client)
        index.row(source.id, root / "a.pdf", "finish")
        index.row(source.id, root / "b.pdf")
        index.row(source.id, root / "sub" / "c.pdf")
        now = client.sources.get(source.id)
        assert now.status is SourceStatus.IN_PROGRESS
        assert now.progress == "1 of 3 files processed"
        index.row(source.id, root / "b.pdf", "finish")
        index.row(source.id, root / "sub" / "c.pdf", "fail")
        done = client.sources.get(source.id)
        assert done.status is SourceStatus.ERROR and done.progress == "3 of 3 files processed"
        index.row(source.id, root / "sub" / "c.pdf", "finish")
        assert client.sources.get(source.id).status is SourceStatus.COMPLETED

    def test_it_is_in_the_serialised_source(self, client, root):
        source = client.sources.create(root)
        data = json.loads(source.to_json())
        assert (data["files_processed"], data["files_total"]) == (0, 0)

    def test_an_unsaved_source_has_no_progress_text(self):
        assert vethuq.sources.Source("x").progress is None

    def test_listing_by_status_uses_the_overall_status(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "a.pdf", "finish")
        listed = client.sources.list(status=SourceStatus.COMPLETED)
        assert [s.id for s in listed] == [source.id]

    def test_purging_forgets_the_files(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "a.pdf", "finish")
        client.sources.remove(source.id)
        client.sources.purge(source.id)
        again = client.sources.create(root)
        assert (again.files_total, again.status) == (0, SourceStatus.PENDING)

    def test_removed_files_stay_known_until_the_purge(self, client, root):
        source = client.sources.create(root)
        Index(client).row(source.id, root / "a.pdf", "finish")
        client.sources.remove(source.id)
        again = client.sources.create(root)
        assert (again.status, again.files_processed, again.files_total) == (
            SourceStatus.COMPLETED,
            1,
            1,
        )


class TestOverlap:
    def test_a_folder_inside_a_source_is_refused(self, client, root):
        client.sources.create(root)
        with pytest.raises(errors.SourceOverlapError) as excinfo:
            client.sources.create(root / "sub")
        assert "inside source" in str(excinfo.value)

    def test_a_file_inside_a_source_is_refused(self, client, root):
        client.sources.create(root)
        with pytest.raises(errors.SourceOverlapError):
            client.sources.create(root / "a.pdf")

    def test_a_folder_containing_a_source_is_refused(self, client, root, tmp_path):
        client.sources.create(root / "sub")
        with pytest.raises(errors.SourceOverlapError) as excinfo:
            client.sources.create(root)
        assert "contains source" in str(excinfo.value)

    def test_siblings_with_a_common_prefix_do_not_overlap(self, client, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs2").mkdir()
        client.sources.create(tmp_path / "docs")
        client.sources.create(tmp_path / "docs2")

    def test_the_same_path_is_still_already_registered(self, client, root):
        client.sources.create(root)
        with pytest.raises(errors.SourceAlreadyExistsError):
            client.sources.create(root)

    def test_a_removed_source_does_not_block(self, client, root):
        first = client.sources.create(root)
        client.sources.remove(first.id)
        client.sources.create(root / "sub")

    def test_reactivating_checks_for_overlap_too(self, client, root):
        first = client.sources.create(root)
        client.sources.remove(first.id)
        client.sources.create(root / "sub")
        with pytest.raises(errors.SourceOverlapError):
            client.sources.create(root)

    def test_the_error_is_a_source_error_with_a_hint(self, client, root):
        client.sources.create(root)
        with pytest.raises(errors.SourceError) as excinfo:
            client.sources.create(root / "sub")
        assert excinfo.value.hint and excinfo.value.exit_code == 25
