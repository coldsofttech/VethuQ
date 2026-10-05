"""How a job follows its run: started, attached to a run, closed with it or when it dies."""

import pytest
from vethuq_core.index import IndexJobs, IndexRunner, IndexState


@pytest.fixture(autouse=True)
def _workers_are_alive(monkeypatch):
    """The pids these tests use belong to no process; count them as running workers."""
    monkeypatch.setattr(IndexRunner, "_is_pid_running", staticmethod(lambda pid: True))


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vethuq.db"


def _state(run_id, error=None):
    return IndexState(
        run_id=run_id,
        pid=4321,
        target=None,
        mode="run",
        status="running",
        total_files=1,
        processed_files=1,
        failed_files=0,
        thread_workers_setting="auto",
        workers=1,
        current_files=[],
        started_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        error=error,
    )


def _running_job(db_path, run_id=5):
    job = IndexJobs.enqueue("1", coalesce=False, db_path=db_path)
    IndexJobs.mark_started(job.id, 4321, db_path)
    IndexJobs.attach_run(job.id, run_id, 4321, db_path)
    return job


def test_a_worker_records_its_run_on_the_job(db_path):
    job = _running_job(db_path, run_id=5)

    done = IndexJobs.get(job.id, db_path)
    assert (done.status, done.run_id, done.pid) == ("running", 5, 4321)
    assert done.started_at is not None


@pytest.mark.parametrize(
    ("run_status", "job_status"),
    [("completed", "completed"), ("stopped", "cancelled"), ("failed", "failed")],
)
def test_a_job_ends_the_way_its_run_does(db_path, monkeypatch, run_status, job_status):
    job = _running_job(db_path, run_id=5)
    monkeypatch.setattr(IndexRunner, "_write_state", staticmethod(lambda *a: None))

    IndexRunner._mark_run_ended(db_path, _state(5, "boom"), run_status)

    done = IndexJobs.get(job.id, db_path)
    assert done.status == job_status
    assert done.finished_at is not None


def test_an_ended_job_is_not_reopened_or_rewritten(db_path):
    job = _running_job(db_path)
    IndexJobs.finish(job.id, "completed", None, db_path)

    IndexJobs.finish(job.id, "failed", "late", db_path)
    IndexJobs.finish_for_run(5, "stopped", None, db_path)

    done = IndexJobs.get(job.id, db_path)
    assert (done.status, done.error) == ("completed", None)


def test_a_job_whose_worker_died_is_failed_when_read(db_path, monkeypatch):
    job = _running_job(db_path)
    monkeypatch.setattr(IndexRunner, "_is_pid_running", staticmethod(lambda pid: False))

    done = IndexJobs.get(job.id, db_path)

    assert done.status == "failed"
    assert done.error == IndexJobs.DIED_MESSAGE


def test_a_job_with_a_live_worker_stays_running(db_path, monkeypatch):
    job = _running_job(db_path)
    monkeypatch.setattr(IndexRunner, "_is_pid_running", staticmethod(lambda pid: True))

    assert IndexJobs.get(job.id, db_path).status == "running"


def test_a_job_the_service_claimed_but_has_no_worker_yet_is_left_alone(db_path, monkeypatch):
    IndexJobs.enqueue("1", db_path=db_path)
    claimed = IndexJobs.claim_next(db_path)
    monkeypatch.setattr(IndexRunner, "_is_pid_running", staticmethod(lambda pid: False))

    assert IndexJobs.get(claimed.id, db_path).status == "running"


def test_pending_lists_waiting_and_running_jobs_oldest_first(db_path):
    first = _running_job(db_path)
    second = IndexJobs.enqueue("2", db_path=db_path)
    done = IndexJobs.enqueue("3", db_path=db_path)
    IndexJobs.finish(done.id, "completed", None, db_path)

    assert [j.id for j in IndexJobs.pending(db_path=db_path)] == [first.id, second.id]
