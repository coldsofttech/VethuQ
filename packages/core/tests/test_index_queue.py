"""Index requests that wait for a worker: `client.index.queue`."""

from __future__ import annotations

import json
import os

import pytest

import tests.fake_pipeline as fp
import vethuq
from vethuq import errors
from vethuq._db import _IndexJob
from vethuq._paths import _Paths
from vethuq.enums import IndexJobStatus
from vethuq.jobs import IndexJob

DEAD_PID = 2**22 + 12345


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.pdf").write_text(fp.pdf_document(fp.native_page("some native words here")))
        client.sources.create(folder)
        yield client


class TestSubmitting:
    def test_a_request_waits_with_what_was_asked(self, client):
        job = client.index.queue.submit(1, workers=2, tier="local", languages="en")
        assert isinstance(job, IndexJob) and job.status is IndexJobStatus.QUEUED
        assert (job.target, job.mode, job.workers, job.tier) == ("1", "run", "2", "local")
        assert job.languages == ("en",) and job.open and job.run_id is None
        assert client.index.queue.get(job.id) == job

    def test_a_bad_mode_or_a_missing_target_is_refused(self, client):
        with pytest.raises(ValueError, match="mode"):
            client.index.queue.submit(mode="forever")
        with pytest.raises(ValueError, match="needs a target"):
            client.index.queue.submit(mode="reindex")

    def test_list_is_newest_first_and_can_filter(self, client):
        a = client.index.queue.submit()
        b = client.index.queue.submit()
        client.index.queue.cancel(a.id)
        assert [j.id for j in client.index.queue.list()] == [b.id, a.id]
        assert [j.id for j in client.index.queue.list(IndexJobStatus.CANCELLED)] == [a.id]
        assert len(client.index.queue.list(limit=1)) == 1

    def test_an_unknown_request(self, client):
        with pytest.raises(errors.IndexJobNotFoundError):
            client.index.queue.get(99)
        with pytest.raises(errors.IndexJobNotFoundError):
            client.index.queue.cancel(99)

    def test_only_a_waiting_request_can_be_cancelled(self, client):
        job = client.index.queue.submit()
        client.index.queue.claim_next()
        with pytest.raises(errors.IndexJobStateError, match="can't be cancelled"):
            client.index.queue.cancel(job.id)

    def test_to_dict_and_json(self, client):
        job = client.index.queue.submit(1)
        assert json.loads(job.to_json())["status"] == "queued" and job.to_dict()["open"]


class TestWorking:
    def test_the_oldest_request_is_taken_once(self, client):
        first = client.index.queue.submit()
        second = client.index.queue.submit()
        taken = client.index.queue.claim_next()
        assert taken.id == first.id and taken.status is IndexJobStatus.RUNNING
        assert taken.pid == os.getpid() and taken.started_at
        assert client.index.queue.claim_next().id == second.id
        assert client.index.queue.claim_next() is None

    def test_run_next_runs_the_request_and_records_its_run(self, client):
        job = client.index.queue.submit()
        done = client.index.queue.run_next()
        assert done.id == job.id and done.status is IndexJobStatus.COMPLETED
        assert done.run_id == client.index.history()[0].id and done.finished_at
        assert client.index.history()[0].files_processed == 1

    def test_nothing_waiting_is_none(self, client):
        assert client.index.queue.run_next() is None

    @pytest.mark.parametrize("mode", ["restart", "reindex", "file"])
    def test_every_mode_runs(self, client, mode):
        client.index.run()
        target = None if mode == "restart" else (1 if mode == "reindex" else None)
        if mode == "file":
            target = str(next(iter(client.sources.list_files(1))).path)
        job = client.index.queue.submit(target, mode=mode)
        assert client.index.queue.run_next().status is IndexJobStatus.COMPLETED
        assert client.index.history()[0].mode == mode if mode != "file" else True
        assert client.index.queue.get(job.id).run_id is not None

    def test_a_bad_request_fails_its_job_and_the_worker_goes_on(self, client):
        bad = client.index.queue.submit(999)
        good = client.index.queue.submit()
        failed = client.index.queue.run_next()
        assert failed.id == bad.id and failed.status is IndexJobStatus.FAILED and failed.error
        assert client.index.queue.run_next().id == good.id

    def test_a_run_going_elsewhere_leaves_the_request_waiting(self, client):
        from vethuq._indexing import _Runs

        job = client.index.queue.submit()
        with client._db().session() as session:  # noqa: SLF001
            run_id = _Runs.begin(session, None, None, 1).id
        try:
            assert client.index.queue.run_next() is None
            assert client.index.queue.get(job.id).status is IndexJobStatus.QUEUED
        finally:
            _Runs.end(run_id)

    def test_a_request_a_dead_worker_took_is_put_back(self, client):
        job = client.index.queue.submit()
        client.index.queue.claim_next(pid=DEAD_PID)
        assert client.index.queue.get(job.id).status is IndexJobStatus.RUNNING
        assert client.index.queue.reconcile() == 1
        again = client.index.queue.claim_next()
        assert again.id == job.id and again.pid == os.getpid()

    def test_status_counts_the_waiting_requests(self, client):
        client.index.run()
        client.index.queue.submit()
        client.index.queue.submit()
        assert client.index.status().queued_jobs == 2
        assert client.index.status().to_dict()["queued_jobs"] == 2

    def test_wait_returns_when_the_request_is_over(self, client):
        job = client.index.queue.submit()
        assert client.index.queue.wait(job.id, timeout=0.05, poll=0.01).open
        client.index.queue.run_next()
        assert not client.index.queue.wait(job.id, timeout=1, poll=0.01).open


class TestTheServiceMarker:
    def test_no_marker_means_no_service(self, client):
        assert client.index.queue.service_running() is False
        assert client.index.queue.service_info() is None

    def test_an_announced_service_is_running_until_it_clears_it(self, client):
        client.index.queue.announce_service()
        assert client.index.queue.service_running() is True
        assert client.index.queue.service_info()["pid"] == os.getpid()
        client.index.queue.clear_service()
        assert client.index.queue.service_running() is False

    def test_a_marker_left_by_a_dead_process_is_ignored(self, client):
        client.index.queue.announce_service(pid=DEAD_PID)
        assert client.index.queue.service_running() is False

    def test_a_damaged_marker_is_ignored(self, client):
        marker = _Paths.run_dir(client._db().db_path) / "service.json"  # noqa: SLF001
        marker.write_text("{not json")
        assert client.index.queue.service_running() is False


_ = _IndexJob
