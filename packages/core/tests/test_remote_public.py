from __future__ import annotations

import json
import sys

import pytest
from sqlalchemy import func, select

import vethuq
from tests import fake_pipeline as fp
from tests import fake_tiers as ft
from vethuq import errors
from vethuq._db import _DocumentIndex, _IndexRun, _PdfPage, _RemoteJobPage
from vethuq._db.values import _JobPageState, _PageState
from vethuq._indexing import _Indexer
from vethuq._indexing.remote import _Outbox, _Remote
from vethuq.enums import FileStatus, IndexRunStatus, RemoteJobStatus
from vethuq.index import RemoteJob
from vethuq_addon_api import JobState
from vethuq_addon_api.testing import FakeExecutor


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "POLL_SECONDS", 0.01)


@pytest.fixture
def remote(tmp_path_factory, monkeypatch):
    """The tier add-on, with an asynchronous `github` executor the test controls."""
    ft.reset()
    folder = tmp_path_factory.mktemp("remote_addon")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    ft.install(folder)
    ft.STATE.github_executor = FakeExecutor(
        default="read remotely", asynchronous=True, state=JobState.RUNNING
    )
    yield ft.STATE.github_executor
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.github")]:
        del sys.modules[name]


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages):
    (folder / name).write_text(fp.pdf_document(*pages), encoding="utf-8")


def files(client, source):
    return {f.name: f.index for f in client.sources.list_files(source.id, detailed=True)}


def db(client, statement):
    with client._db().session() as session:
        return session.scalars(statement).all()


class TestSending:
    def test_pages_that_need_ocr_are_sent_and_the_run_waits_for_them(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page(), fp.native_page())
        write(root, "text.pdf", fp.native_page("only native text in this one, which is long"))
        source = client.sources.create(root)
        run = client.index.run(tier="github")
        assert run.tier == "github" and run.status is IndexRunStatus.WAITING_REMOTE
        assert "away" in run.error
        listed = files(client, source)
        assert listed["text.pdf"].status is FileStatus.INDEXED  # nothing to send
        assert listed["scan.pdf"].status is FileStatus.PROCESSING
        assert (run.files_total, run.files_processed, run.files_failed) == (2, 1, 0)
        (job,) = client.index.jobs()
        assert isinstance(job, RemoteJob) and job.status is RemoteJobStatus.SUBMITTED
        assert (job.tier, job.images, job.run_id) == ("github", 1, run.id)
        assert job.credits == 1.0
        assert [r.key.split(".")[-1] for r in remote.seen] == ["1:0"]

    def test_the_images_are_paid_for_when_they_are_staged(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page(), fp.scanned_page("another page"))
        client.sources.create(root)
        run = client.index.run(tier="github")
        assert run.credits_charged == 2.0 and run.ocr_pages == 2
        assert client.credits.balance("github").daily == 18
        assert client.credits.balance("local").daily == 500
        assert {e.wallet for e in client.credits.history(kind="charge")} == {"github"}

    def test_the_pages_wait_in_the_database(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page("x"), fp.native_page())
        client.sources.create(root)
        client.index.run(tier="github")
        pages = {p.page_number: p for p in db(client, select(_PdfPage))}
        assert pages[1].status is _PageState.DISPATCHED and pages[1].text == ""
        assert pages[2].status is _PageState.DONE  # native pages are final at once
        (image,) = db(client, select(_RemoteJobPage))
        assert image.state is _JobPageState.SENT and image.job_id is not None

    def test_a_mixed_page_sends_each_image(self, remote, client, root):
        write(root, "m.pdf", fp.mixed_page("Native text with enough words in it.", "a", "b",
                                           region_side=100))  # fmt: skip
        client.sources.create(root)
        run = client.index.run(tier="github")
        assert len(remote.seen) == 2 and run.status is IndexRunStatus.WAITING_REMOTE
        assert [r.key.split(".")[-1] for r in remote.seen] == ["1:0", "1:1"]
        (job,) = client.index.jobs()
        assert job.images == 2

    def test_jobs_are_limited_in_size(self, remote, client, root):
        client.settings.tiers.set_max_job_pages(2)
        write(root, "a.pdf", *[fp.scanned_page(f"page {n} text") for n in range(5)])
        client.sources.create(root)
        client.index.run(tier="github")
        assert sorted(j.images for j in client.index.jobs()) == [1, 2, 2]
        assert len(remote.jobs) == 3

    def test_jobs_are_limited_in_bytes(self, remote, client, root, monkeypatch):
        from vethuq._indexing import remote as module

        monkeypatch.setattr(module, "_size", lambda image: 600_000)
        client.settings.tiers.set_max_job_megabytes(1)
        write(root, "a.pdf", *[fp.scanned_page(f"page {n} text") for n in range(3)])
        client.sources.create(root)
        client.index.run(tier="github")
        assert sorted(j.images for j in client.index.jobs()) == [1, 1, 1]
        assert client.index.jobs()[0].size_bytes == 600_000

    def test_a_failed_send_gives_the_pages_and_credits_back(self, remote, client, root):
        def broken(requests):
            raise ConnectionError("no route")

        remote.submit = broken
        write(root, "a.pdf", fp.scanned_page())
        source = client.sources.create(root)
        run = client.index.run(tier="github")
        assert run.status is IndexRunStatus.COMPLETED and client.index.jobs() == []
        assert files(client, source)["a.pdf"].status is FileStatus.PENDING
        assert client.credits.balance("github").daily == 20
        assert len(client.credits.history(kind="refund")) == 1
        assert db(client, select(_RemoteJobPage)) == []
        assert db(client, select(_PdfPage))[0].status is _PageState.WAITING

    def test_a_run_that_dies_before_sending_is_cleaned_up_by_the_next(
        self, remote, client, root, monkeypatch
    ):
        monkeypatch.setattr(_Outbox, "_send", lambda self: setattr(self, "entries", []))
        write(root, "a.pdf", fp.scanned_page())
        source = client.sources.create(root)
        run = client.index.run(tier="github")
        assert client.credits.balance("github").daily == 19  # paid, never sent
        assert run.status is IndexRunStatus.COMPLETED
        assert files(client, source)["a.pdf"].status is FileStatus.PENDING
        monkeypatch.undo()
        client.index.run(tier="github")  # recovers the staged image, then sends it again
        assert len(client.credits.history(kind="refund")) == 1
        assert client.credits.balance("github").daily == 19  # charged once in the end
        assert len(client.index.jobs()) == 1

    def test_a_tier_that_is_gone_leaves_its_jobs_alone(self, remote, client, root):
        write(root, "a.pdf", fp.scanned_page())
        client.sources.create(root)
        client.index.run(tier="github")
        manager = client._manager()
        manager._discover = lambda: []
        manager.reload()
        assert client.index.collect() == []
        assert [j.status for j in client.index.jobs()] == [RemoteJobStatus.SUBMITTED]


class TestCollecting:
    def test_finished_jobs_are_imported(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page(), fp.native_page())
        source = client.sources.create(root)
        run = client.index.run(tier="github")
        remote.state = JobState.DONE
        ended = client.index.collect()
        assert [j.status for j in ended] == [RemoteJobStatus.COMPLETED]
        info = files(client, source)["scan.pdf"]
        assert info.status is FileStatus.INDEXED and info.pages == 2 and info.languages == ["en"]
        pages = {p.page_number: p for p in db(client, select(_PdfPage))}
        assert pages[1].text == "read remotely" and pages[1].status is _PageState.DONE
        assert pages[1].confidence == 0.9
        finished = client.index.get(run.id)
        assert finished.status is IndexRunStatus.COMPLETED and finished.error is None
        assert (finished.files_processed, finished.pages_processed) == (1, 2)
        assert client.index.collect() == []  # nothing left to do

    def test_the_results_show_in_statistics_and_credits(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        client.index.run(tier="github")
        remote.state = JobState.DONE
        client.index.collect()
        total = client.stats.overview().total
        assert (total.ocr_pages, total.credits) == (1, 1.0)
        assert client.stats.overview(engine="fake-executor 1.0").total.pages == 1
        assert client.credits.balance("github").daily == 19  # paid once, at the send

    def test_a_mixed_page_joins_the_text_of_its_images(self, remote, client, root):
        write(root, "m.pdf", fp.mixed_page("Native text with enough words in it.", "a", "b",
                                           region_side=100))  # fmt: skip
        client.sources.create(root)
        client.index.run(tier="github")
        remote.state = JobState.DONE
        client.index.collect()
        (page,) = db(client, select(_PdfPage))
        assert page.text == "Native text with enough words in it.\nread remotely\nread remotely"
        assert page.source.value == "mixed" and page.status is _PageState.DONE

    def test_waiting_for_the_jobs(self, remote, client, root):
        remote.state = JobState.DONE
        write(root, "scan.pdf", fp.scanned_page())
        source = client.sources.create(root)
        run = client.index.run(tier="github", wait=True)
        assert run.status is IndexRunStatus.COMPLETED
        assert files(client, source)["scan.pdf"].status is FileStatus.INDEXED
        assert client.index.jobs()[0].status is RemoteJobStatus.COMPLETED

    def test_waiting_gives_up_at_the_timeout(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        run = client.index.run(tier="github", wait=True, timeout=0.001)
        assert run.status is IndexRunStatus.WAITING_REMOTE
        assert client.index.collect(wait=True, timeout=0.001) == []

    def test_waiting_picks_the_result_up_when_it_arrives(self, remote, client, root, monkeypatch):
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        polls = []
        original = remote.poll

        def poll(handle):
            polls.append(handle)
            if len(polls) >= 3:
                remote.state = JobState.DONE
            return original(handle)

        remote.poll = poll
        assert client.index.run(tier="github", wait=True, timeout=1).status is (
            IndexRunStatus.COMPLETED
        )
        assert len(polls) >= 3

    def test_the_default_timeout_is_a_setting(self, remote, client, root):
        client.settings.tiers.set_wait_timeout_minutes(1)
        remote.state = JobState.DONE
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        assert client.index.run(tier="github", wait=True).status is IndexRunStatus.COMPLETED

    def test_the_next_run_collects_what_came_back(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page())
        source = client.sources.create(root)
        first = client.index.run(tier="github")
        remote.state = JobState.DONE
        second = client.index.run(tier="local")
        assert files(client, source)["scan.pdf"].status is FileStatus.INDEXED
        assert second.files_total == 0
        assert client.index.get(first.id).status is IndexRunStatus.COMPLETED

    def test_a_run_while_a_job_is_out_sends_nothing_twice(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page())
        source = client.sources.create(root)
        client.index.run(tier="github")
        again = client.index.run(tier="github")
        assert again.files_total == 0 and len(client.index.jobs()) == 1
        assert files(client, source)["scan.pdf"].status is FileStatus.PROCESSING
        assert client.credits.balance("github").daily == 19

    def test_a_failed_job_gives_everything_back_and_the_next_run_sends_again(
        self, remote, client, root
    ):
        write(root, "scan.pdf", fp.scanned_page())
        source = client.sources.create(root)
        client.index.run(tier="github")
        remote.state = JobState.FAILED
        (ended,) = client.index.collect()
        assert ended.status is RemoteJobStatus.FAILED and "failure" in ended.error
        assert client.credits.balance("github").daily == 20
        assert db(client, select(_RemoteJobPage)) == []
        remote.state = JobState.DONE
        run = client.index.run(tier="github", wait=True)
        assert run.status is IndexRunStatus.COMPLETED
        assert files(client, source)["scan.pdf"].status is FileStatus.INDEXED
        assert [j.status for j in client.index.jobs()] == [
            RemoteJobStatus.COMPLETED,
            RemoteJobStatus.FAILED,
        ]

    def test_a_job_that_takes_too_long_expires(self, remote, client, root, monkeypatch):
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        client.index.run(tier="github")
        monkeypatch.setattr(_Remote, "EXPIRE_HOURS", -1)
        (ended,) = client.index.collect()
        assert ended.status is RemoteJobStatus.EXPIRED and "too long" in ended.error
        assert remote.cancelled == ["job-1"]
        assert client.credits.balance("github").daily == 20

    def test_an_image_that_comes_back_empty_is_sent_again_later(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page(), fp.scanned_page("second page"))
        client.sources.create(root)
        client.index.run(tier="github")
        remote.state = JobState.DONE
        original = remote.collect

        def partial(handle):
            results = original(handle)
            first = sorted(results)[0]
            return {first: results[first]}

        remote.collect = partial
        (ended,) = client.index.collect()
        assert ended.status is RemoteJobStatus.COMPLETED and "empty" in ended.error
        assert client.credits.balance("github").daily == 19  # one image's charge came back
        statuses = sorted(p.status.value for p in db(client, select(_PdfPage)))
        assert statuses == ["done", "waiting"]

    def test_a_job_that_will_not_answer_is_left_for_later(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        client.index.run(tier="github")

        def broken(handle):
            raise ConnectionError("down")

        remote.poll = broken
        assert client.index.collect() == []
        assert client.index.jobs()[0].status is RemoteJobStatus.SUBMITTED

    def test_results_for_a_purged_source_are_dropped_quietly(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page())
        source = client.sources.create(root)
        client.index.run(tier="github")
        client.sources.remove(source.id)
        client.sources.purge(source.id)
        remote.state = JobState.DONE
        (ended,) = client.index.collect()
        assert ended.status is RemoteJobStatus.COMPLETED
        assert db(client, select(_PdfPage)) == []

    def test_a_modified_file_while_its_pages_are_away(self, remote, client, root):
        import os
        import time

        write(root, "scan.pdf", fp.scanned_page("first version"))
        source = client.sources.create(root)
        client.index.run(tier="github")
        write(root, "scan.pdf", fp.scanned_page("second version, quite different"))
        os.utime(root / "scan.pdf", (time.time() + 9, time.time() + 9))
        remote.state = JobState.DONE
        run = client.index.run(tier="github", wait=True)
        assert run.status is IndexRunStatus.COMPLETED
        assert files(client, source)["scan.pdf"].status is FileStatus.INDEXED
        assert db(client, select(func.count()).select_from(_DocumentIndex)) == [1]


class TestDuplicatesAndLanguages:
    def test_identical_files_send_once_and_finish_together(self, remote, client, root):
        write(root, "a.pdf", fp.scanned_page("same"))
        write(root, "b.pdf", fp.scanned_page("same"))
        source = client.sources.create(root)
        run = client.index.run(tier="github", workers=0)
        assert len(remote.seen) == 1 and run.credits_charged == 1.0
        assert {i.status for i in files(client, source).values()} == {FileStatus.PROCESSING}
        remote.state = JobState.DONE
        client.index.collect()
        assert {i.status for i in files(client, source).values()} == {FileStatus.INDEXED}
        assert client.index.get(run.id).files_processed == 2

    def test_the_same_in_parallel(self, remote, client, root):
        for n in range(4):
            write(root, f"{n}.pdf", fp.scanned_page("same"))
        client.sources.create(root)
        run = client.index.run(tier="github", workers=4)
        assert len(remote.seen) == 1 and run.credits_charged == 1.0


class TestJobs:
    @pytest.fixture
    def busy(self, remote, client, root):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        client.index.run(tier="github")
        remote.state = JobState.FAILED
        client.index.collect()
        remote.state = JobState.RUNNING
        client.index.run(tier="github")
        return remote

    def test_listing(self, busy, client):
        jobs = client.index.jobs()
        assert [j.id for j in jobs] == [2, 1]
        assert [j.id for j in client.index.jobs(order="asc")] == [1, 2]
        assert [j.id for j in client.index.jobs(status="failed")] == [1]
        assert [j.id for j in client.index.jobs(status=RemoteJobStatus.SUBMITTED)] == [2]
        assert [j.id for j in client.index.jobs(tier="github")] == [2, 1]
        assert client.index.jobs(tier="nope") == []
        assert [j.id for j in client.index.jobs(run_id=jobs[0].run_id)] == [2]
        assert [j.id for j in client.index.jobs(limit=1, offset=1)] == [1]

    def test_bad_arguments(self, busy, client):
        for kwargs, error in (
            ({"status": "nope"}, ValueError),
            ({"order": "up"}, ValueError),
            ({"limit": -1}, ValueError),
            ({"offset": -1}, ValueError),
        ):
            with pytest.raises(error):
                client.index.jobs(**kwargs)
        for bad in (0, -1, True, "5"):
            with pytest.raises(ValueError):
                client.index.collect(timeout=bad)
        with pytest.raises(TypeError):
            client.index.run(wait="yes")

    def test_collecting_one_run(self, busy, client):
        busy.state = JobState.DONE
        other = client.index.jobs()[0].run_id + 100
        assert client.index.collect(other) == []
        assert [j.id for j in client.index.collect(client.index.jobs()[0].run_id)] == [2]

    def test_dict_and_json(self, busy, client):
        job = client.index.jobs()[0]
        assert job.to_dict()["status"] == "submitted"
        assert json.loads(job.to_json()) == job.to_dict()

    def test_purging_a_source_leaves_the_job_record(self, busy, client):
        (source,) = client.sources.list()
        client.sources.remove(source.id)
        client.sources.purge(source.id)
        assert len(client.index.jobs()) == 2
        with client._db().session() as session:
            assert session.scalar(select(func.count()).select_from(_IndexRun)) == 2


class TestLocalIsUnchanged:
    def test_a_local_run_ignores_the_remote_tier(self, remote, client, root):
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        run = client.index.run()
        assert run.tier == "local" and run.status is IndexRunStatus.COMPLETED
        assert client.index.jobs() == []

    def test_errors_for_remote_tiers_that_are_off(self, remote, client, root):
        ft.STATE.github_available, ft.STATE.github_reason = False, "not set up"
        write(root, "scan.pdf", fp.scanned_page())
        client.sources.create(root)
        with pytest.raises(errors.TierUnavailableError, match="not set up"):
            client.index.run(tier="github")
