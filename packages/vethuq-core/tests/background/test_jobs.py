import pytest
from vethuq_core.background import IndexJobs


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vethuq.db"


def test_a_job_is_queued_and_claimed_in_order(db_path):
    first = IndexJobs.enqueue("1", db_path=db_path)
    second = IndexJobs.enqueue(None, restart=True, languages="te", db_path=db_path)

    claimed = IndexJobs.claim_next(db_path)

    assert claimed.id == first.id
    assert claimed.status == "running"
    assert [j.id for j in IndexJobs.queued(db_path)] == [second.id]
    assert IndexJobs.queued(db_path)[0].restart is True
    assert IndexJobs.queued(db_path)[0].languages == "te"


def test_claiming_from_an_empty_queue_returns_none(db_path):
    assert IndexJobs.claim_next(db_path) is None


def test_an_identical_waiting_job_is_reused(db_path):
    one = IndexJobs.enqueue("1", db_path=db_path)
    again = IndexJobs.enqueue("1", db_path=db_path)
    other = IndexJobs.enqueue("2", db_path=db_path)
    restart = IndexJobs.enqueue("1", restart=True, db_path=db_path)

    assert again.id == one.id
    assert len({one.id, other.id, restart.id}) == 3
    assert len(IndexJobs.queued(db_path)) == 3


def test_finishing_a_job_records_how_it_ended(db_path):
    job = IndexJobs.enqueue("1", db_path=db_path)
    IndexJobs.claim_next(db_path)

    IndexJobs.finish(job.id, "failed", "boom", db_path)

    done = IndexJobs.get(job.id, db_path)
    assert (done.status, done.error) == ("failed", "boom")
    assert done.finished_at is not None


def test_a_job_left_running_is_requeued(db_path):
    job = IndexJobs.enqueue("1", db_path=db_path)
    IndexJobs.claim_next(db_path)

    assert IndexJobs.requeue_running(db_path) == 1

    assert IndexJobs.get(job.id, db_path).status == "queued"


def test_cancel_queued_leaves_a_running_job_alone(db_path):
    running = IndexJobs.enqueue("1", db_path=db_path)
    IndexJobs.claim_next(db_path)
    waiting = IndexJobs.enqueue("2", db_path=db_path)

    assert IndexJobs.cancel_queued(db_path) == 1

    assert IndexJobs.get(running.id, db_path).status == "running"
    assert IndexJobs.get(waiting.id, db_path).status == "cancelled"


def test_prune_keeps_only_the_most_recent_finished_jobs(db_path, monkeypatch):
    monkeypatch.setattr(IndexJobs, "KEEP_FINISHED", 2)
    ids = []
    for target in ("1", "2", "3"):
        job = IndexJobs.enqueue(target, db_path=db_path)
        IndexJobs.claim_next(db_path)
        IndexJobs.finish(job.id, "completed", None, db_path)
        ids.append(job.id)
    waiting = IndexJobs.enqueue("4", db_path=db_path)

    IndexJobs.prune(db_path)

    assert IndexJobs.get(ids[0], db_path) is None
    assert IndexJobs.get(ids[1], db_path) is not None
    assert IndexJobs.get(waiting.id, db_path).status == "queued"
