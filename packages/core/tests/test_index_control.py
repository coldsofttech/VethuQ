"""Pause, resume and stop a run; run again only what failed; read files again."""

from __future__ import annotations

import sys
import threading
import time

import pytest
from sqlalchemy import select

import vethuq
from tests import fake_pipeline as fp
from vethuq import errors
from vethuq._db import _PdfPage, _PdfPagePhase, _PdfPageQuick
from vethuq._indexing import _Indexer
from vethuq.enums import FileStatus, IndexRunStatus


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "CONTROL_SECONDS", 0.02)
    monkeypatch.setattr(_Indexer, "QUICK_CHECK_SECONDS", 3600.0)


@pytest.fixture
def phases(tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.mktemp("phase_addons")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    fp.install(folder, fp.DEEPER)
    yield
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
        if name.rsplit(".", 1)[-1] in {"ocr_moderate", "ocr_deep"}:
            del sys.modules[name]


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages, **extra):
    path = folder / name
    path.write_text(fp.pdf_document(*pages, **extra), encoding="utf-8")
    return path


def statuses(client, source):
    return {f.name: f.index.status for f in client.sources.list_files(source.id, detailed=True)}


def rows(client, model):
    with client._db().session() as session:
        return list(session.scalars(select(model)))


def when_reading(monkeypatch, action, *, times=1):
    """Run `action` the first `times` times the OCR engine reads something."""
    original = fp.FakeEngine.recognize
    count = {"n": 0}

    def recognize(self, image, angle=0):
        count["n"] += 1
        if count["n"] <= times:
            action()
        return original(self, image, angle)

    monkeypatch.setattr(fp.FakeEngine, "recognize", recognize)


class TestNothingGoing:
    @pytest.mark.parametrize("method", ["pause", "resume", "stop"])
    def test_no_run_to_control(self, client, method):
        with pytest.raises(errors.IndexNotRunningError):
            getattr(client.index, method)()

    def test_a_finished_run_is_not_going(self, client, root):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        client.index.run()
        with pytest.raises(errors.IndexNotRunningError):
            client.index.pause()


class TestPauseAndResume:
    def test_a_paused_run_waits_and_carries_on_when_resumed(self, client, root, monkeypatch):
        for n in range(4):
            write(root, f"{n}.pdf", fp.scanned_page(f"page of file number {n}"))
        source = client.sources.create(root)
        seen = {}

        def watcher():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                status = client.index.status()
                if status and status.paused:
                    time.sleep(0.15)  # it must stay put while paused
                    again = client.index.status()
                    seen["paused"] = (status.phase, again.run.files_processed, status.current_files)
                    client.index.resume()
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=watcher)
        when_reading(monkeypatch, client.index.pause)
        thread.start()
        run = client.index.run()
        thread.join()
        assert run.status is IndexRunStatus.COMPLETED and run.files_processed == 4
        phase, processed, _ = seen["paused"]
        assert phase == "quick" and processed == 1  # the first file was done, then it waited
        assert set(statuses(client, source).values()) == {FileStatus.INDEXED}

    def test_resume_does_nothing_to_a_run_that_is_not_paused(self, client, root, monkeypatch):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        when_reading(monkeypatch, client.index.resume)
        assert client.index.run().status is IndexRunStatus.COMPLETED


class TestStop:
    def test_the_run_ends_stopped_and_the_next_one_finishes_the_rest(
        self, client, root, monkeypatch
    ):
        for n in range(4):
            write(root, f"{n}.pdf", fp.scanned_page(f"page of file number {n}"))
        source = client.sources.create(root)
        when_reading(monkeypatch, lambda: client.index.stop(wait=False))
        run = client.index.run()
        assert run.status is IndexRunStatus.STOPPED and run.error == "Stopped."
        assert run.files_processed == 1
        done = statuses(client, source)
        assert list(done.values()).count(FileStatus.INDEXED) == 1
        assert list(done.values()).count(FileStatus.PENDING) == 3
        status = client.index.status()
        assert status.finished and not status.active and status.control == "run"
        monkeypatch.undo()
        again = client.index.run()
        assert again.status is IndexRunStatus.COMPLETED and again.files_processed == 3
        assert set(statuses(client, source).values()) == {FileStatus.INDEXED}

    def test_a_file_stopped_part_way_keeps_its_pages(self, client, root, monkeypatch):
        write(root, "a.pdf", *[fp.scanned_page(f"page {n} words") for n in range(1, 5)])
        source = client.sources.create(root)
        when_reading(monkeypatch, lambda: client.index.stop(wait=False), times=2)
        run = client.index.run()
        assert run.status is IndexRunStatus.STOPPED
        assert statuses(client, source)["a.pdf"] is FileStatus.PENDING
        kept = len(rows(client, _PdfPage))
        assert 1 <= kept < 4
        monkeypatch.undo()
        client.index.run()
        assert len(rows(client, _PdfPage)) == 4
        assert statuses(client, source)["a.pdf"] is FileStatus.INDEXED

    def test_a_stopped_run_in_its_deeper_phases(self, phases, client, root, monkeypatch):
        write(root, "a.pdf", *[fp.scanned_page(f"page {n} words") for n in range(1, 4)])
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        calls = []
        original = fp.FakeEngine.recognize

        def recognize(self, image, angle=0):
            if angle:
                calls.append(angle)
                if len(calls) == 1:
                    client.index.stop(wait=False)
            return original(self, image, angle)

        monkeypatch.setattr(fp.FakeEngine, "recognize", recognize)
        run = client.index.run()
        assert run.status is IndexRunStatus.STOPPED
        assert len(calls) < 9  # not every angle of every page
        assert len(rows(client, _PdfPage)) == 3  # quick finished before moderate began


class TestRestart:
    def test_only_the_files_that_failed_are_tried_again(self, client, root):
        write(root, "good.pdf", fp.scanned_page("good words here"))
        write(root, "bad.pdf", fp.scanned_page("bad file"), flaky=1)  # fails once, then reads
        source = client.sources.create(root)
        first = client.index.run()
        assert first.files_failed == 1 and statuses(client, source)["bad.pdf"] is FileStatus.ERROR
        write(root, "new.pdf", fp.scanned_page("a new file"))
        run = client.index.restart()
        assert run.mode == "restart" and run.status is IndexRunStatus.COMPLETED
        assert (run.files_total, run.files_processed, run.files_failed) == (1, 1, 0)
        done = statuses(client, source)
        assert done["bad.pdf"] is FileStatus.INDEXED
        assert done["new.pdf"] is FileStatus.PENDING  # restart leaves new files alone

    def test_nothing_failed_nothing_to_do(self, client, root):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        client.index.run()
        assert client.index.restart().files_total == 0


class TestReindex:
    def test_every_file_is_read_again_and_stays_searchable_meanwhile(
        self, client, root, monkeypatch
    ):
        write(root, "a.pdf", fp.scanned_page("old words in the file"))
        write(root, "b.pdf", fp.native_page("only native words in this one, which is long"))
        source = client.sources.create(root)
        client.index.run()
        fp.STATE.ocr_calls.clear()
        found = []
        original = fp.FakeEngine.recognize

        def recognize(self, image, angle=0):
            found.append(len(client.search.run("old").matches))  # asked in the middle of reading
            result = original(self, image, angle)
            return type(result)(
                **{
                    **result.__dict__,
                    "text": "new words in the file",
                    "lines": (("new words in the file", 0.8),),
                }
            )

        monkeypatch.setattr(fp.FakeEngine, "recognize", recognize)
        run = client.index.reindex(source.id)
        assert run.mode == "reindex" and (run.files_total, run.files_processed) == (2, 2)
        assert found and all(count >= 1 for count in found)  # the old pages stayed searchable
        assert {m.file_name for m in client.search.run("new words").matches} == {"a.pdf"}
        assert client.search.run("old").matches == []
        assert set(statuses(client, source).values()) == {FileStatus.INDEXED}

    def test_a_native_file_is_read_again_too(self, client, root):
        write(root, "n.pdf", fp.native_page("only native words in this one, which is long"))
        source = client.sources.create(root)
        client.index.run()
        fp.STATE.reads.clear()
        client.index.reindex(source.id)
        assert len(fp.STATE.reads) >= 1

    def test_it_costs_credits_again(self, client, root):
        write(root, "a.pdf", fp.scanned_page("words"))
        source = client.sources.create(root)
        assert client.index.run().credits_charged == 1.0
        assert client.index.reindex(source.id).credits_charged == 1.0

    def test_the_deeper_phases_are_read_again_with_it(self, phases, client, root):
        write(root, "a.pdf", fp.at_angles(fp.scanned_page("upright"), a90="sideways"))
        source = client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        fp.STATE.angle_calls.clear()
        client.index.reindex(source.id)
        assert [a for _, a in fp.STATE.angle_calls] == [90, 180, 270]
        assert len(rows(client, _PdfPagePhase)) == 1
        assert len(rows(client, _PdfPageQuick)) == 1  # one quick read, not two

    def test_a_file_that_fails_to_read_again_keeps_its_pages_and_its_status(
        self, client, root, monkeypatch
    ):
        path = write(root, "a.pdf", fp.scanned_page("old words in the file"))
        source = client.sources.create(root)
        client.index.run()
        # Reading it again fails (the file is damaged now, but has the same content hash).
        original = fp.FakeReader.read

        def read(self, file_path, page_number=None):
            raise fp.CorruptedFileError(file_path, "not valid")
            yield  # pragma: no cover

        monkeypatch.setattr(fp.FakeReader, "read", read)
        run = client.index.reindex(source.id)
        monkeypatch.setattr(fp.FakeReader, "read", original)
        assert run.files_failed == 1
        assert statuses(client, source)["a.pdf"] is FileStatus.INDEXED
        assert len(client.search.run("old").matches) == 1
        info = client.sources.list_files(source.id, detailed=True)[0].index
        assert "Reading it again failed" in info.error
        assert path.exists()

    def test_a_target_is_needed(self, client):
        with pytest.raises(TypeError):
            client.index.reindex(None)


class TestReindexFile:
    def test_by_path(self, client, root):
        a = write(root, "a.pdf", fp.scanned_page("first file words"))
        write(root, "b.pdf", fp.scanned_page("second file words"))
        client.sources.create(root)
        client.index.run()
        fp.STATE.ocr_calls.clear()
        run = client.index.reindex_file(a)
        assert run.mode == "file" and (run.files_total, run.files_processed) == (1, 1)
        assert len(fp.STATE.ocr_calls) == 1

    def test_by_document_id(self, client, root):
        write(root, "a.pdf", fp.scanned_page("first file words"))
        client.sources.create(root)
        client.index.run()
        (page,) = rows(client, _PdfPage)
        run = client.index.reindex_file(page.document_id)
        assert run.files_processed == 1

    def test_a_file_that_is_not_tracked(self, client, root, tmp_path):
        write(root, "a.pdf", fp.scanned_page("words"))
        client.sources.create(root)
        client.index.run()
        elsewhere = tmp_path / "x.pdf"
        elsewhere.write_text("{}")
        for missing in (elsewhere, root / "nope.pdf", 999):
            with pytest.raises(errors.FileNotTrackedError):
                client.index.reindex_file(missing)
        with pytest.raises(TypeError):
            client.index.reindex_file(None)

    def test_a_file_gone_from_disk_is_not_tracked(self, client, root):
        gone = write(root, "a.pdf", fp.scanned_page("words"))
        write(root, "b.pdf", fp.scanned_page("other words"))
        client.sources.create(root)
        client.index.run()
        gone.unlink()
        client.index.run()  # notices it has gone
        with pytest.raises(errors.FileNotTrackedError):
            client.index.reindex_file(gone)


class TestStatusFields:
    def test_a_finished_run_reports_no_live_details(self, client, root):
        write(root, "a.pdf", fp.scanned_page("one"))
        (root / "x.docx").write_text("unsupported")
        client.sources.create(root)
        client.index.run()
        status = client.index.status()
        assert (status.phase, status.current_files, status.workers_active) == ("", (), 0)
        assert status.unsupported_files == 1 and status.deepened_pages == 0
        assert (status.paused, status.stopping) == (False, False)
        assert status.to_dict()["unsupported_files"] == 1

    def test_while_it_runs(self, client, root, monkeypatch):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        seen = {}

        def look():
            status = client.index.status()
            seen.update(
                phase=status.phase, files=status.current_files, active=status.active,
                workers=status.workers_active,
            )  # fmt: skip

        when_reading(monkeypatch, look)
        client.index.run()
        assert seen["phase"] == "quick" and seen["active"] and len(seen["files"]) == 1
        assert seen["files"][0].endswith("a.pdf")

    def test_deepened_pages_are_counted(self, phases, client, root):
        write(root, "a.pdf", fp.scanned_page("one"), fp.scanned_page("two"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        assert client.index.status().deepened_pages == 2
