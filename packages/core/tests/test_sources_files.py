from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest

import vethuq
from vethuq import errors
from vethuq._sources import _Files


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


@pytest.fixture
def tree(tmp_path):
    """docs/ with files at several depths, plus a lone file next to it."""
    root = tmp_path / "docs"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "b.pdf").write_text("bb")
    (root / "A.pdf").write_text("a")
    (root / "sub" / "c.pdf").write_text("ccc")
    (root / "sub" / "deep" / "d.txt").write_text("dddd")
    (root / ".hidden").write_text("h")
    lone = tmp_path / "lone.pdf"
    lone.write_text("lonely")
    return root, lone


class TestSourcesListFiles:
    def test_a_folder_lists_every_file_under_it(self, client, tree):
        root, _ = tree
        source = client.sources.create(root)

        files = client.sources.list_files(source.id)

        assert [f.relative_path for f in files] == [
            ".hidden",
            "A.pdf",
            "b.pdf",
            "sub/c.pdf",
            "sub/deep/d.txt",
        ]

    def test_files_are_sorted_ignoring_case(self, client, tree):
        source = client.sources.create(tree[0])

        names = [f.name for f in client.sources.list_files(source.id)]

        assert names.index("A.pdf") < names.index("b.pdf")

    def test_a_file_source_returns_that_same_file(self, client, tree):
        _, lone = tree
        source = client.sources.create(lone)

        (file,) = client.sources.list_files(source.id)

        assert file.path == str(lone.resolve())
        assert file.name == "lone.pdf"
        assert file.relative_path == "lone.pdf"
        assert file.size_bytes == len("lonely")

    def test_by_path(self, client, tree):
        root, lone = tree
        client.sources.create(root)
        client.sources.create(lone)

        assert len(client.sources.list_files(root)) == 5
        assert [f.name for f in client.sources.list_files(str(lone))] == ["lone.pdf"]

    def test_paths_are_absolute_and_inside_the_folder(self, client, tree):
        root, _ = tree
        source = client.sources.create(root)

        for file in client.sources.list_files(source.id):
            assert os.path.isabs(file.path)
            assert file.path == str(root.resolve() / file.relative_path)

    def test_sizes_and_modified_times(self, client, tree):
        root, _ = tree
        source = client.sources.create(root)
        os.utime(root / "b.pdf", (1_700_000_000, 1_700_000_000))

        by_name = {f.name: f for f in client.sources.list_files(source.id)}

        assert by_name["b.pdf"].size_bytes == 2
        assert by_name["d.txt"].size_bytes == 4
        modified = datetime.fromisoformat(by_name["b.pdf"].modified_at)
        assert modified == datetime.fromtimestamp(1_700_000_000, UTC)
        assert modified.utcoffset().total_seconds() == 0

    def test_empty_folders_and_empty_sources_give_nothing(self, client, tmp_path):
        (tmp_path / "nothing" / "inner").mkdir(parents=True)
        source = client.sources.create(tmp_path / "nothing")

        assert client.sources.list_files(source.id) == []

    def test_the_list_reflects_the_disk_now(self, client, tree):
        root, _ = tree
        source = client.sources.create(root)
        (root / "new.pdf").write_text("n")
        (root / "b.pdf").unlink()

        names = [f.name for f in client.sources.list_files(source.id)]

        assert "new.pdf" in names and "b.pdf" not in names

    def test_links_to_folders_are_not_followed(self, client, tree):
        root, _ = tree
        (root / "sub" / "loop").symlink_to(root, target_is_directory=True)
        source = client.sources.create(root)

        paths = [f.relative_path for f in client.sources.list_files(source.id)]

        assert paths == [".hidden", "A.pdf", "b.pdf", "sub/c.pdf", "sub/deep/d.txt"]

    def test_links_to_files_are_listed_and_broken_links_skipped(self, client, tree):
        root, lone = tree
        (root / "link.pdf").symlink_to(lone)
        (root / "broken.pdf").symlink_to(root / "missing.pdf")
        source = client.sources.create(root)

        names = [f.name for f in client.sources.list_files(source.id)]

        assert "link.pdf" in names and "broken.pdf" not in names

    def test_unknown_source_is_not_found(self, client, tree):
        with pytest.raises(errors.SourceNotFoundError):
            client.sources.list_files(9)

    def test_a_removed_source_is_not_found(self, client, tree):
        source = client.sources.create(tree[0])
        client.sources.remove(source.id)

        with pytest.raises(errors.SourceNotFoundError):
            client.sources.list_files(source.id)

    def test_a_folder_that_was_deleted_is_reported(self, client, tree):
        root, _ = tree
        source = client.sources.create(root)
        for path in sorted(root.rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        root.rmdir()

        with pytest.raises(errors.SourcePathError) as excinfo:
            client.sources.list_files(source.id)

        assert str(root.resolve()) in excinfo.value.message
        assert "remove the source" in excinfo.value.hint

    def test_a_file_that_was_deleted_is_reported(self, client, tree):
        _, lone = tree
        source = client.sources.create(lone)
        lone.unlink()

        with pytest.raises(errors.SourcePathError):
            client.sources.list_files(source.id)

    def test_results_are_source_files(self, client, tree):
        source = client.sources.create(tree[0])

        assert all(isinstance(f, vethuq.SourceFile) for f in client.sources.list_files(source.id))

    def test_a_folder_source_whose_path_became_a_file_lists_that_file(self, client, tree):
        root, _ = tree
        source = client.sources.create(root)
        for path in sorted(root.rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        root.rmdir()
        root.write_text("now a file")

        (file,) = client.sources.list_files(source.id)

        assert file.name == "docs" and file.size_bytes == len("now a file")


class TestSourceFile:
    def test_to_dict_and_json(self):
        file = vethuq.SourceFile(
            path="/a/b.pdf",
            relative_path="b.pdf",
            name="b.pdf",
            size_bytes=3,
            modified_at="2026-01-01T00:00:00+00:00",
        )

        assert file.to_dict() == {
            "path": "/a/b.pdf",
            "relative_path": "b.pdf",
            "name": "b.pdf",
            "size_bytes": 3,
            "modified_at": "2026-01-01T00:00:00+00:00",
        }
        assert json.loads(file.to_json()) == file.to_dict()
        assert "\n" in file.to_json(indent=2)

    def test_is_frozen(self):
        file = vethuq.SourceFile("/a", "a", "a", 1, "t")
        with pytest.raises(AttributeError):
            file.name = "b"

    def test_is_exported_from_the_package(self):
        assert vethuq.SourceFile is vethuq.sources.SourceFile


class TestFiles:
    def test_a_missing_path_is_a_source_path_error(self, tmp_path):
        with pytest.raises(errors.SourcePathError):
            _Files.list(tmp_path / "nowhere")

    def test_a_file_that_vanishes_during_the_scan_is_skipped(self, tmp_path, monkeypatch):
        (tmp_path / "a.pdf").write_text("a")
        (tmp_path / "b.pdf").write_text("b")
        real = _Files.entry

        def flaky(path, root):
            return None if path.name == "a.pdf" else real(path, root)

        monkeypatch.setattr(_Files, "entry", staticmethod(flaky))

        assert [e.name for e in _Files.list(tmp_path)] == ["b.pdf"]
