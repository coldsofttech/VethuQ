"""The free text file types (txt, csv, markdown), read by their real add-ons."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

import vethuq
from vethuq._db import _CsvPage, _MarkdownPage, _PdfPage, _TxtPage
from vethuq._indexing import _Indexer
from vethuq.enums import FileStatus


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def index(client, root):
    source = client.sources.create(root)
    run = client.index.run(source.id)
    statuses = {f.name: f.index.status for f in client.sources.list_files(source.id, detailed=True)}
    return run, statuses


def rows(client, model):
    with client._database.session() as session:  # noqa: SLF001
        return session.scalars(select(model)).all()


class TestTextFiles:
    def test_short_files_are_indexed_without_ocr(self, client, root):
        (root / "a.txt").write_text("Hi")
        (root / "b.csv").write_text("x,y\n")
        (root / "c.md").write_text("ok\n")
        run, statuses = index(client, root)
        assert set(statuses.values()) == {FileStatus.INDEXED}
        assert (run.files_processed, run.ocr_pages, run.credits_charged) == (3, 0, 1.5)  # native pages: 0.5 each

    def test_they_are_found_by_search(self, client, root):
        (root / "a.txt").write_text("zebra crossing")
        (root / "b.csv").write_text("name,city\nAda,Zurich\n")
        (root / "c.md").write_text("# Title\n\nSome **bold** giraffe words.\n")
        index(client, root)
        for word, name in [("zebra", "a.txt"), ("Zurich", "b.csv"), ("giraffe", "c.md")]:
            assert [m.file_name for m in client.search.run(word).matches] == [name]

    def test_each_type_keeps_its_details_in_its_own_table(self, client, root):
        (root / "a.txt").write_text("plain words here")
        (root / "b.csv").write_text("a;b;c\n1;2;3\n4;5;6\n")
        (root / "c.md").write_text("# Title\n")
        index(client, root)
        (txt,), (csv,), (md,) = (rows(client, m) for m in (_TxtPage, _CsvPage, _MarkdownPage))
        assert txt.encoding == "utf-8"
        assert (csv.encoding, csv.delimiter, csv.row_count, csv.column_count) == (
            "utf-8", ";", 3, 3,
        )  # fmt: skip
        assert (md.encoding, md.image_count) == ("utf-8", 0)
        assert len(rows(client, _PdfPage)) == 3  # the text of all three is in the page table

    def test_details_go_when_the_page_does(self, client, root):
        (root / "a.txt").write_text("plain words here")
        source = client.sources.create(root)
        client.index.run(source.id)
        with client._database.session() as session:  # noqa: SLF001
            for page in session.scalars(select(_PdfPage)):
                session.delete(page)
        assert rows(client, _TxtPage) == []

    def test_binary_data_fails_the_file(self, client, root):
        (root / "a.txt").write_bytes(bytes(range(256)) * 8)
        _, statuses = index(client, root)
        assert statuses["a.txt"] is FileStatus.ERROR


class TestMarkdownPictures:
    def test_the_quick_phase_leaves_the_pictures_to_the_moderate_phase(self, client, root, caplog):
        (root / "door.png").write_bytes(b"not really a png")
        (root / "c.md").write_text("# Doors\n\nA red door.\n\n![The door](door.png)\n")
        with caplog.at_level(logging.WARNING, logger="vethuq.indexing"):
            run, statuses = index(client, root)
        assert statuses["c.md"] is FileStatus.INDEXED
        assert run.ocr_pages == 0
        # Nothing is said about the picture yet: moderate is the phase that reads it (and says
        # so when no add-on reads its format; see test_ocr_phases).
        assert not [r for r in caplog.records if "door.png" in r.getMessage()]
        assert {m.file_name for m in client.search.run("door").matches} == {"c.md"}
        (md,) = rows(client, _MarkdownPage)
        assert md.image_count == 1
        (page,) = [p for p in rows(client, _PdfPage)]
        assert page.deepen_from == "moderate"

    def test_remote_and_missing_pictures_are_not_warned_about(self, client, root, caplog):
        (root / "c.md").write_text("![a](http://x.test/a.png)\n\n![b](gone.png)\n\nWords here.\n")
        with caplog.at_level(logging.WARNING, logger="vethuq.indexing"):
            _, statuses = index(client, root)
        assert statuses["c.md"] is FileStatus.INDEXED
        assert not [r for r in caplog.records if "was not read" in r.getMessage()]


class TestMarkdownPicturesWithTheImageAddOn:
    """With an add-on that reads the picture's format, the picture is read like an image file."""

    @pytest.fixture
    def png(self, tmp_path_factory, monkeypatch):
        import sys

        from tests import fake_pipeline

        folder = tmp_path_factory.mktemp("png_addon")
        monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
        fake_pipeline.install(
            folder, {"png": ("vethuq_addon_png", "FakePngAddon")}
        )  # already installed once by the autouse fixture; this adds png
        yield
        for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
            if name.rsplit(".", 1)[-1] == "png":
                del sys.modules[name]

    def test_quick_reads_the_image_file_but_not_the_picture_in_the_markdown(
        self, png, tmp_path, root
    ):
        (root / "door.png").write_text("RED DOOR NUMBER SEVEN", encoding="utf-8")
        (root / "c.md").write_text("# Doors\n\nA page about doors.\n\n![d](door.png)\n")
        with vethuq.VethuQ(db_path=tmp_path / "db2" / "vethuq.db") as client:
            client.settings.index.set_stability_check_seconds(0)
            run, statuses = index(client, root)
            assert statuses["c.md"] is FileStatus.INDEXED
            assert statuses["door.png"] is FileStatus.INDEXED  # the image is a file of its own too
            assert run.ocr_pages == 1  # the image file; the picture in the Markdown waits
            found = client.search.run("seven").matches
            assert {m.file_name for m in found} == {"door.png"}
