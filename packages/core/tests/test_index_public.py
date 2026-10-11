from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

import vethuq
from tests import fake_pipeline as fp
from tests.language_addons import TELUGU, LanguageAddonFactory
from vethuq import errors
from vethuq._db import (
    _Document,
    _DocumentIndex,
    _DocumentLanguage,
    _IndexRun,
    _PdfPage,
    _PdfPageQuick,
    _Source,
)
from vethuq._indexing import _Indexer
from vethuq._indexing.runs import _Runs
from vethuq.enums import FileStatus, IndexRunSortBy, IndexRunStatus, SortOrder, SourceStatus
from vethuq.index import Index, IndexRun


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        yield client


@pytest.fixture
def telugu(tmp_path_factory, monkeypatch):
    """Telugu installed; ask for it before `client`, which loads the add-ons when first used."""
    folder = tmp_path_factory.mktemp("telugu")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    LanguageAddonFactory.install(folder, "telugu", [TELUGU])


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages, **extra):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fp.pdf_document(*pages, **extra), encoding="utf-8")
    return path


def files(client, source):
    return {f.relative_path: f.index for f in client.sources.list_files(source.id, detailed=True)}


def pages(client, name=None):
    with client._db().session() as session:
        rows = session.scalars(
            select(_PdfPage).order_by(_PdfPage.document_id, _PdfPage.page_number)
        )
        return [(p.page_number, p.text, p.source.value, round(p.confidence, 2)) for p in rows]


class TestRun:
    def test_a_native_pdf_is_indexed_without_ocr(self, client, root):
        write(root, "a.pdf", fp.native_page("one two three four five six"), fp.native_page())
        source = client.sources.create(root)
        run = client.index.run(source.id)
        assert isinstance(run, IndexRun)
        assert run.status is IndexRunStatus.COMPLETED
        assert (run.files_total, run.files_processed, run.files_failed) == (1, 1, 0)
        assert run.source_id == source.id and run.target == source.path and run.file_path is None
        assert run.completed_at and run.error is None
        assert fp.STATE.ocr_calls == []
        assert [p[2] for p in pages(client)] == ["native", "native"]
        info = files(client, source)["a.pdf"]
        assert info.status is FileStatus.INDEXED
        assert (info.pages, info.confidence, info.languages, info.file_type) == (
            2,
            1.0,
            ["en"],
            "pdf",
        )

    def test_a_scanned_page_is_read_by_ocr(self, client, root):
        write(root, "s.pdf", fp.scanned_page("hello from the scan"))
        source = client.sources.create(root)
        client.index.run()
        assert pages(client) == [(1, "hello from the scan", "ocr", 0.8)]
        assert len(fp.STATE.ocr_calls) == 1
        with client._db().session() as session:
            quick = session.scalars(select(_PdfPageQuick)).one()
            assert (quick.region_count, quick.engine) == (0, "fake-ocr 1.0")
        assert files(client, source)["s.pdf"].confidence == 0.8

    def test_a_mixed_page_reads_only_its_images(self, client, root):
        write(
            root,
            "m.pdf",
            fp.mixed_page("Native text with enough words in it.", "pic one", "pic two"),
        )
        client.sources.create(root)
        client.index.run()
        (page,) = pages(client)
        assert page[2] == "mixed"
        assert page[1] == "Native text with enough words in it.\npic one\npic two"
        assert [call[1][0] for call in fp.STATE.ocr_calls] == ["region", "region"]
        with client._db().session() as session:
            assert session.scalars(select(_PdfPageQuick)).one().region_count == 2

    def test_a_page_with_a_little_text_is_scanned(self, client, root):
        write(root, "t.pdf", {"text": "Page 1", "ocr": "the real words are in the image"})
        client.sources.create(root)
        client.index.run()
        assert pages(client)[0][1:3] == ("the real words are in the image", "ocr")

    def test_running_again_leaves_indexed_files_alone(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        client.index.run()
        reads = len(fp.STATE.reads)
        run = client.index.run()
        assert (run.files_total, run.files_processed) == (0, 0)
        assert len(fp.STATE.reads) == reads

    def test_the_source_reports_progress(self, client, root):
        write(root, "a.pdf", fp.native_page())
        write(root, "b.pdf", fp.native_page("different words entirely in this one"))
        source = client.sources.create(root)
        assert (
            client.sources.get(source.id).progress == "0 of 0 files processed"
        )  # nothing is known before a run
        client.index.run()
        done = client.sources.get(source.id)
        assert done.status is SourceStatus.COMPLETED and done.progress == "2 of 2 files processed"
        assert done.last_scanned_at

    def test_inline_with_no_workers(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        assert client.index.run(workers=0).workers == 0

    def test_workers_in_parallel(self, client, root):
        for n in range(6):
            write(root, f"{n}.pdf", fp.native_page(f"document number {n} has some words"))
        client.sources.create(root)
        run = client.index.run(workers=3)
        assert (run.workers, run.files_processed) == (3, 6)

    def test_the_workers_setting_applies(self, client, root):
        client.settings.index.set_workers(2)
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        assert client.index.run().workers == 2

    def test_auto_workers_are_between_one_and_eight(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        assert 1 <= client.index.run(workers="auto").workers <= 8

    def test_bad_workers_are_refused(self, client, root):
        client.sources.create(root)
        with pytest.raises(errors.InvalidSettingValueError):
            client.index.run(workers=9)

    def test_non_pdf_files_are_unsupported_and_untouched(self, client, root):
        (root / "n.txt").write_text("hi")
        source = client.sources.create(root)
        run = client.index.run()
        assert run.files_total == 0
        assert files(client, source)["n.txt"].status is FileStatus.UNSUPPORTED


class TestChanges:
    def test_a_modified_file_is_read_again(self, client, root):
        path = write(root, "a.pdf", fp.native_page("first version of the words here"))
        source = client.sources.create(root)
        client.index.run()
        write(root, "a.pdf", fp.native_page("second version of the words here, longer"))
        os.utime(path, (time.time() + 5, time.time() + 5))
        assert files(client, source)["a.pdf"].status is FileStatus.MODIFIED
        client.index.run()
        assert pages(client)[0][1].startswith("second version")
        with client._db().session() as session:
            assert session.scalar(select(func.count()).select_from(_Document)) == 1  # old dropped

    def test_a_removed_file_is_marked_removed(self, client, root):
        path = write(root, "a.pdf", fp.native_page())
        source = client.sources.create(root)
        client.index.run()
        path.unlink()
        client.index.run()
        info = files(client, source)["a.pdf"]
        assert (info.status, info.on_disk) == (FileStatus.REMOVED, False)

    def test_a_new_file_is_picked_up(self, client, root):
        write(root, "a.pdf", fp.native_page())
        source = client.sources.create(root)
        client.index.run()
        write(root, "b.pdf", fp.native_page("brand new words for a second file"))
        run = client.index.run()
        assert run.files_total == 1
        assert files(client, source)["b.pdf"].status is FileStatus.INDEXED

    def test_a_file_that_vanishes_while_reading_is_removed(self, client, root):
        write(root, "a.pdf", fp.native_page(), error="removed")
        source = client.sources.create(root)
        run = client.index.run()
        with client._db().session() as session:
            assert session.scalars(select(_DocumentIndex)).one().status is FileStatus.REMOVED
        assert run.files_failed == 0
        assert source.id

    def test_files_that_changed_during_the_stability_wait_are_read_as_they_are(self, client, root):
        client.settings.index.set_stability_check_seconds(0.05)
        path = write(root, "a.pdf", fp.native_page("some stable words in this one"))
        client.sources.create(root)
        assert client.index.run().files_processed == 1
        assert path.exists()


class TestDuplicates:
    def test_identical_files_share_one_document(self, client, root):
        write(root, "a.pdf", fp.scanned_page("shared scan"))
        write(root, "b.pdf", fp.scanned_page("shared scan"))
        source = client.sources.create(root)
        client.index.run(workers=0)
        assert len(fp.STATE.ocr_calls) == 1
        listed = files(client, source)
        assert listed["a.pdf"].duplicate_of is None
        assert listed["b.pdf"].duplicate_of == str(root / "a.pdf")
        assert listed["b.pdf"].pages == 1
        with client._db().session() as session:
            assert session.scalar(select(func.count()).select_from(_Document)) == 1
            assert session.scalar(select(func.count()).select_from(_PdfPage)) == 1

    def test_identical_files_in_parallel_are_read_once(self, client, root):
        for n in range(4):
            write(root, f"{n}.pdf", fp.scanned_page("same scan"))
        client.sources.create(root)
        client.index.run(workers=4)
        assert len(fp.STATE.ocr_calls) == 1

    def test_a_document_read_in_another_language_is_read_again_and_merged(
        self, telugu, client, tmp_path
    ):
        folders = []
        for name, language in (("en", "en"), ("te", "te")):
            folder = tmp_path / name
            folder.mkdir()
            write(folder, "a.pdf", fp.scanned_page("english words"), fp.native_page())
            folders.append(client.sources.create(folder, languages=[language]))
        client.index.run(folders[0].id)
        client.index.run(folders[1].id)
        with client._db().session() as session:
            assert session.scalar(select(func.count()).select_from(_Document)) == 1
            assert len(session.scalars(select(_DocumentLanguage)).all()) == 2
            assert session.scalar(select(func.count()).select_from(_PdfPageQuick)) == 2
        assert fp.STATE.engines_created == ["en", "te"]
        assert pages(client)[0][1].count("english words") == 1  # the same text isn't doubled
        assert pages(client)[1][2] == "native"  # native pages aren't read again

    def test_an_all_native_document_is_shared_across_languages(self, telugu, client, tmp_path):
        folders = []
        for name, language in (("en", "en"), ("te", "te")):
            folder = tmp_path / name
            folder.mkdir()
            write(folder, "a.pdf", fp.native_page())
            folders.append(client.sources.create(folder, languages=[language]))
        client.index.run(folders[0].id)
        reads = len(fp.STATE.reads)
        client.index.run(folders[1].id)
        assert len(fp.STATE.reads) == reads  # no second read of the same content


class TestFailures:
    def test_a_failing_file_is_an_error_and_the_run_goes_on(self, client, root):
        write(root, "bad.pdf", fp.native_page(), error="boom")
        write(root, "good.pdf", fp.native_page("these words are fine and readable"))
        source = client.sources.create(root)
        run = client.index.run(workers=0)
        assert run.status is IndexRunStatus.COMPLETED
        assert (run.files_total, run.files_processed, run.files_failed) == (2, 2, 1)
        listed = files(client, source)
        assert listed["bad.pdf"].status is FileStatus.ERROR
        assert "boom" in listed["bad.pdf"].error and listed["bad.pdf"].retry_count == 1
        assert listed["good.pdf"].status is FileStatus.INDEXED
        assert client.sources.get(source.id).status is SourceStatus.ERROR

    def test_a_flaky_file_is_retried_within_the_run(self, client, root):
        write(root, "f.pdf", fp.native_page(), flaky=2)
        source = client.sources.create(root)
        run = client.index.run(workers=0)
        assert run.files_failed == 0
        assert files(client, source)["f.pdf"].status is FileStatus.INDEXED
        assert len(fp.STATE.reads) == 3

    def test_retry_attempts_come_from_the_setting(self, client, root):
        client.settings.index.set_retry_attempts(0)
        write(root, "f.pdf", fp.native_page(), error="boom")
        client.sources.create(root)
        client.index.run(workers=0)
        assert len(fp.STATE.reads) == 1

    def test_a_failed_file_is_tried_again_by_the_next_run(self, client, root):
        write(root, "f.pdf", fp.native_page(), error="boom")
        source = client.sources.create(root)
        client.index.run()
        write(root, "f.pdf", fp.native_page("fixed and readable now, no more error"))
        # the content changed, so it is a modified file; touch to be sure
        os.utime(root / "f.pdf", (time.time() + 9, time.time() + 9))
        run = client.index.run()
        assert run.files_failed == 0
        assert files(client, source)["f.pdf"].status is FileStatus.INDEXED

    def test_an_unchanged_error_file_is_retried_each_run(self, client, root):
        write(root, "f.pdf", fp.native_page(), error="boom")
        client.sources.create(root)
        client.index.run(workers=0)
        reads = len(fp.STATE.reads)
        client.index.run(workers=0)
        assert len(fp.STATE.reads) > reads

    def test_a_damaged_file_is_an_error_without_retrying(self, client, root):
        write(root, "c.pdf", fp.native_page(), error="corrupt")
        source = client.sources.create(root)
        client.index.run(workers=0)
        assert len(fp.STATE.reads) == 1
        assert "damaged" in files(client, source)["c.pdf"].error

    def test_a_password_protected_file_is_unsupported(self, client, root):
        write(root, "p.pdf", fp.native_page(), error="password")
        source = client.sources.create(root)
        run = client.index.run()
        info = files(client, source)["p.pdf"]
        assert info.status is FileStatus.UNSUPPORTED and "password" in info.error
        assert run.files_failed == 0
        reads = len(fp.STATE.reads)
        client.index.run()
        assert len(fp.STATE.reads) == reads  # left alone until it changes

    def test_a_scanned_page_without_the_ocr_engine_is_an_error(self, client, root):
        fp.STATE.engine_available = False
        write(root, "s.pdf", fp.scanned_page())
        write(root, "n.pdf", fp.native_page("a native one that needs no ocr at all"))
        source = client.sources.create(root)
        client.index.run(workers=0)
        listed = files(client, source)
        assert listed["s.pdf"].status is FileStatus.ERROR
        assert "OCR isn't available" in listed["s.pdf"].error
        assert listed["n.pdf"].status is FileStatus.INDEXED

    def test_a_missing_engine_is_not_retried(self, client, root):
        fp.STATE.engine_available = False
        write(root, "s.pdf", fp.scanned_page())
        client.sources.create(root)
        client.index.run(workers=0)
        assert len(fp.STATE.reads) == 1

    def test_a_missing_quick_phase_is_an_error(self, client, root):
        fp.STATE.phase_available = False
        write(root, "s.pdf", fp.scanned_page())
        source = client.sources.create(root)
        client.index.run(workers=0)
        assert "quick OCR phase" in files(client, source)["s.pdf"].error

    def test_models_that_cannot_be_downloaded_fail_the_file(self, client, root):
        fp.STATE.download_fails = {"det-mobile"}
        write(root, "s.pdf", fp.scanned_page())
        source = client.sources.create(root)
        client.index.run(workers=0)
        assert "download" in files(client, source)["s.pdf"].error

    def test_unsupported_files_are_checked_again_when_an_addon_arrives(self, client, root):
        fp.STATE.pdf_available = False
        write(root, "a.pdf", fp.native_page())
        source = client.sources.create(root)
        assert client.index.run().files_total == 0
        assert files(client, source)["a.pdf"].status is FileStatus.UNSUPPORTED
        fp.STATE.pdf_available = True
        assert client.index.run().files_processed == 1
        assert files(client, source)["a.pdf"].status is FileStatus.INDEXED


class TestTargets:
    def test_a_single_file_in_a_source(self, client, root):
        a = write(root, "a.pdf", fp.native_page())
        write(root, "b.pdf", fp.native_page("other words that differ from file a"))
        source = client.sources.create(root)
        run = client.index.run(a)
        assert run.files_total == 1
        assert run.file_path == str(a) and run.target == str(a) and run.source_id == source.id
        listed = files(client, source)
        assert listed["a.pdf"].status is FileStatus.INDEXED
        assert listed["b.pdf"].status is FileStatus.PENDING

    def test_a_source_by_path(self, client, root):
        write(root, "a.pdf", fp.native_page())
        client.sources.create(root)
        assert client.index.run(str(root)).files_processed == 1

    def test_a_file_source(self, client, root):
        path = write(root, "only.pdf", fp.native_page())
        client.sources.create(path)
        assert client.index.run(path).files_processed == 1

    def test_everything_runs_every_source(self, client, tmp_path):
        for name in ("x", "y"):
            folder = tmp_path / name
            folder.mkdir()
            write(folder, "a.pdf", fp.native_page(f"words in folder {name} for the test"))
            client.sources.create(folder)
        run = client.index.run()
        assert (run.source_id, run.target, run.files_processed) == (None, None, 2)

    def test_an_unknown_target_is_refused(self, client, root, tmp_path):
        client.sources.create(root)
        with pytest.raises(errors.SourceNotFoundError):
            client.index.run(999)
        with pytest.raises(errors.SourceNotFoundError):
            client.index.run(tmp_path / "elsewhere.pdf")
        with pytest.raises(TypeError):
            client.index.run(1.5)

    def test_a_removed_source_is_refused(self, client, root):
        source = client.sources.create(root)
        client.sources.remove(source.id)
        with pytest.raises(errors.SourceNotFoundError):
            client.index.run(source.id)

    def test_a_source_gone_from_disk_fails_the_run(self, client, tmp_path):
        folder = tmp_path / "gone"
        folder.mkdir()
        source = client.sources.create(folder)
        folder.rmdir()
        with pytest.raises(errors.SourcePathError):
            client.index.run(source.id)
        (failed,) = client.index.history()
        assert failed.status is IndexRunStatus.FAILED and "no longer exists" in failed.error

    def test_a_language_on_the_source_is_used(self, telugu, client, root):
        write(root, "s.pdf", fp.scanned_page())
        client.sources.create(root, languages=["te"])
        client.index.run()
        assert fp.STATE.engines_created == ["te"]

    def test_the_default_languages_setting_is_used(self, client, root):
        write(root, "s.pdf", fp.scanned_page())
        client.sources.create(root)
        client.index.run()
        assert fp.STATE.engines_created == ["en"]


class TestRunsRecord:
    def test_only_one_run_at_a_time(self, client, root):
        client.sources.create(root)
        with client._db().session() as session:
            _Runs.begin(session, None, None, 1)
        with pytest.raises(errors.IndexAlreadyRunningError):
            client.index.run()
        _Runs.end(1)

    def test_a_run_left_behind_by_a_dead_process_is_failed_and_files_reset(self, client, root):
        write(root, "a.pdf", fp.native_page())
        source = client.sources.create(root)
        client.index.run()
        with client._db().session() as session:
            session.add(
                _IndexRun(
                    status=IndexRunStatus.RUNNING,
                    pid=2**22 + 12345,
                    started_at=datetime.now(UTC).isoformat(),
                )
            )
        run = client.index.run()
        assert run.status is IndexRunStatus.COMPLETED
        stale = [r for r in client.index.history() if r.status is IndexRunStatus.FAILED]
        assert len(stale) == 1 and "ended before" in stale[0].error
        assert source.id

    def test_a_run_of_this_process_that_is_not_active_is_stale(self, client, root):
        client.sources.create(root)
        with client._db().session() as session:
            session.add(
                _IndexRun(
                    status=IndexRunStatus.RUNNING,
                    pid=os.getpid(),
                    started_at=datetime.now(UTC).isoformat(),
                )
            )
        assert client.index.run().status is IndexRunStatus.COMPLETED

    def test_get_and_not_found(self, client, root):
        client.sources.create(root)
        run = client.index.run()
        assert client.index.get(run.id) == run
        with pytest.raises(errors.IndexRunNotFoundError):
            client.index.get(999)
        with pytest.raises(TypeError):
            client.index.get("1")

    def test_to_dict_and_json(self, client, root):
        client.sources.create(root)
        run = client.index.run()
        data = run.to_dict()
        assert data["status"] == "completed" and data["files_total"] == 0
        assert json.loads(run.to_json()) == data

    def test_a_failure_inside_a_run_fails_it(self, client, root, monkeypatch):
        client.sources.create(root)

        def boom(*args, **kwargs):
            raise RuntimeError("discovery broke")

        monkeypatch.setattr(_Indexer, "_discover", boom)
        with pytest.raises(RuntimeError):
            client.index.run()
        (run,) = client.index.history()
        assert run.status is IndexRunStatus.FAILED and run.error == "discovery broke"
        monkeypatch.undo()
        assert client.index.run().status is IndexRunStatus.COMPLETED  # nothing left running

    def test_an_interrupt_stops_the_run(self, client, root, monkeypatch):
        client.sources.create(root)

        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(_Indexer, "_discover", interrupted)
        with pytest.raises(KeyboardInterrupt):
            client.index.run()
        assert client.index.history()[0].status is IndexRunStatus.STOPPED


class TestHistory:
    @pytest.fixture
    def runs(self, client, tmp_path):
        folders = []
        for name in ("one", "two"):
            folder = tmp_path / name
            folder.mkdir()
            write(folder, "a.pdf", fp.native_page(f"some words that belong to {name} here"))
            folders.append(client.sources.create(folder))
        client.index.run(folders[0].id)
        client.index.run(folders[1].id)
        client.index.run()
        return folders

    def test_newest_first_by_default(self, client, runs):
        history = client.index.history()
        assert [r.id for r in history] == [3, 2, 1]

    def test_sorting(self, client, runs):
        assert [r.id for r in client.index.history(order=SortOrder.ASC)] == [1, 2, 3]
        by_total = client.index.history(sort_by=IndexRunSortBy.FILES_TOTAL, order="asc")
        assert [r.files_total for r in by_total] == sorted(r.files_total for r in by_total)
        assert client.index.history(sort_by="id", order="desc")[0].id == 3

    def test_filtering_by_source_id_and_path(self, client, runs):
        assert [r.id for r in client.index.history(runs[0].id)] == [1]
        assert [r.id for r in client.index.history(runs[1].path)] == [2]
        assert client.index.history(12345) == []

    def test_filtering_by_status(self, client, runs):
        assert len(client.index.history(status="completed")) == 3
        assert client.index.history(status=IndexRunStatus.FAILED) == []

    def test_filtering_by_time(self, client, runs):
        now = datetime.now(UTC)
        assert len(client.index.history(started_after=now - timedelta(minutes=5))) == 3
        assert client.index.history(started_after=now + timedelta(minutes=5)) == []
        assert len(client.index.history(started_before=now.isoformat())) == 3
        assert client.index.history(started_before=now - timedelta(days=1)) == []
        naive = datetime.now() - timedelta(days=1)  # noqa: DTZ005
        assert len(client.index.history(started_after=naive.replace(tzinfo=None))) == 3

    def test_paging(self, client, runs):
        assert [r.id for r in client.index.history(limit=2)] == [3, 2]
        assert [r.id for r in client.index.history(limit=2, offset=2)] == [1]

    def test_bad_values_are_refused(self, client, runs):
        with pytest.raises(ValueError):
            client.index.history(status="nope")
        with pytest.raises(ValueError):
            client.index.history(sort_by="nope")
        with pytest.raises(ValueError):
            client.index.history(order="sideways")
        with pytest.raises(ValueError):
            client.index.history(started_after="yesterday")
        with pytest.raises(TypeError):
            client.index.history(started_after=5)
        with pytest.raises(ValueError):
            client.index.history(limit=-1)
        with pytest.raises(TypeError):
            client.index.history(target=1.5)

    def test_a_file_run_is_found_by_its_file(self, client, tmp_path):
        folder = tmp_path / "f"
        folder.mkdir()
        a = write(folder, "a.pdf", fp.native_page())
        client.sources.create(folder)
        client.index.run(a)
        assert len(client.index.history(a)) == 1
        assert client.index.history(folder) == []  # a run of the whole source it wasn't


class TestPurge:
    def test_purging_a_source_deletes_its_runs_and_pages_only(self, client, tmp_path):
        folders = []
        for name in ("p", "q"):
            folder = tmp_path / name
            folder.mkdir()
            write(folder, "a.pdf", fp.scanned_page(f"scan of {name}"))
            folders.append(client.sources.create(folder))
        client.index.run(folders[0].id)
        client.index.run(folders[1].id)
        client.index.run()
        client.sources.remove(folders[0].id)
        client.sources.purge(folders[0].id)
        remaining = client.index.history()
        assert [r.source_id for r in remaining] == [None, folders[1].id]
        with client._db().session() as session:
            assert session.scalar(select(func.count()).select_from(_PdfPage)) == 1
            assert session.scalar(select(func.count()).select_from(_PdfPageQuick)) == 1
            assert session.scalar(select(func.count()).select_from(_Source)) == 1

    def test_expired_sources_take_their_runs_too(self, client, root):
        write(root, "a.pdf", fp.native_page())
        source = client.sources.create(root)
        client.index.run(source.id)
        client.sources.remove(source.id)
        client.sources.purge_expired(0)
        assert client.index.history() == []


class TestIndexClass:
    def test_it_is_the_index_class(self, client):
        assert isinstance(client.index, Index)
        assert client.index is client.index
