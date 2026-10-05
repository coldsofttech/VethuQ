import pytest
from vethuq_core.background import IndexJobs
from vethuq_core.background.host import ServiceHost
from vethuq_core.index import AlreadyRunningError, IndexRunner, IndexState


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vethuq.db"


@pytest.fixture
def host(db_path):
    host = ServiceHost(db_path)
    host.POLL_SECONDS = 0.01
    host.RUN_POLL_SECONDS = 0.01
    return host


def _state(status, error=None):
    return IndexState(
        run_id=1,
        pid=4321,
        target=None,
        mode="run",
        status=status,
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


def _fake_run(monkeypatch, *, ends_as, started=None, alive_polls=1):
    """Make `start_run` succeed and the worker die after `alive_polls` checks."""
    started = started if started is not None else []
    polls = {"n": 0}

    def start_run(target=None, **kwargs):
        started.append((target, kwargs))
        return 4321

    def alive(pid):
        polls["n"] += 1
        return polls["n"] <= alive_polls

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(start_run))
    monkeypatch.setattr(ServiceHost, "_alive", staticmethod(alive))
    monkeypatch.setattr(IndexRunner, "read_state", staticmethod(lambda *a, **k: ends_as))
    monkeypatch.setattr(IndexRunner, "is_running", staticmethod(lambda *a, **k: (False, None)))
    return started


def test_a_job_runs_with_its_own_settings_and_completes(db_path, host, monkeypatch):
    started = _fake_run(monkeypatch, ends_as=_state("completed"))
    job = IndexJobs.enqueue("7", restart=True, languages="te", db_path=db_path)

    host._tick()

    target, kwargs = started[0]
    assert (target, kwargs["restart"], kwargs["languages"]) == ("7", True, "te")
    assert kwargs["db_path"] == db_path
    assert IndexJobs.get(job.id, db_path).status == "completed"


def test_a_failed_run_records_its_error(db_path, host, monkeypatch):
    _fake_run(monkeypatch, ends_as=_state("failed", "worker crashed"))
    job = IndexJobs.enqueue(None, db_path=db_path)

    host._tick()

    done = IndexJobs.get(job.id, db_path)
    assert (done.status, done.error) == ("failed", "worker crashed")


def test_a_run_stopped_from_outside_is_cancelled_not_resumed(db_path, host, monkeypatch):
    _fake_run(monkeypatch, ends_as=_state("stopped"))
    job = IndexJobs.enqueue(None, db_path=db_path)

    host._tick()

    assert IndexJobs.get(job.id, db_path).status == "cancelled"


def test_a_job_that_cannot_start_is_failed_with_the_reason(db_path, host, monkeypatch):
    def start_run(target=None, **kwargs):
        raise ValueError("source gone")

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(start_run))
    monkeypatch.setattr(IndexRunner, "is_running", staticmethod(lambda *a, **k: (False, None)))
    job = IndexJobs.enqueue("7", db_path=db_path)

    host._tick()

    done = IndexJobs.get(job.id, db_path)
    assert (done.status, done.error) == ("failed", "source gone")


def test_a_job_waits_when_another_run_wins_the_race(db_path, host, monkeypatch):
    def start_run(target=None, **kwargs):
        raise AlreadyRunningError("busy")

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(start_run))
    monkeypatch.setattr(IndexRunner, "is_running", staticmethod(lambda *a, **k: (False, None)))
    job = IndexJobs.enqueue("7", db_path=db_path)

    host._tick()

    assert IndexJobs.get(job.id, db_path).status == "queued"


def test_nothing_starts_while_a_one_off_run_is_active(db_path, host, monkeypatch):
    started = _fake_run(monkeypatch, ends_as=_state("completed"))
    monkeypatch.setattr(IndexRunner, "is_running", staticmethod(lambda *a, **k: (True, 99)))
    job = IndexJobs.enqueue(None, db_path=db_path)

    host._tick()

    assert started == []
    assert IndexJobs.get(job.id, db_path).status == "queued"


def test_nothing_starts_while_paused(db_path, host, monkeypatch):
    started = _fake_run(monkeypatch, ends_as=_state("completed"))
    job = IndexJobs.enqueue(None, db_path=db_path)

    host.pause()
    host._tick()
    assert started == []
    assert IndexJobs.get(job.id, db_path).status == "queued"

    host.resume()
    host._tick()
    assert IndexJobs.get(job.id, db_path).status == "completed"


def test_pausing_the_service_pauses_its_active_run_and_resuming_resumes_it(
    db_path, host, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        IndexRunner, "request_pause", staticmethod(lambda db_path=None: calls.append("pause"))
    )
    monkeypatch.setattr(
        IndexRunner, "request_resume", staticmethod(lambda db_path=None: calls.append("resume"))
    )

    host._sync_pause()
    assert calls == []
    host.pause()
    host._sync_pause()
    host._sync_pause()
    host.resume()
    host._sync_pause()

    assert calls == ["pause", "resume"]


def test_stopping_the_service_hands_the_run_back_to_the_queue(db_path, host, monkeypatch):
    _fake_run(monkeypatch, ends_as=_state("stopped"), alive_polls=10_000)
    stopped = []
    monkeypatch.setattr(
        IndexRunner, "request_stop", staticmethod(lambda db_path=None: stopped.append(True))
    )
    job = IndexJobs.enqueue(None, db_path=db_path)
    host.stop()

    host._tick()

    assert stopped == [True]
    assert IndexJobs.get(job.id, db_path).status == "queued"


def test_start_up_requeues_jobs_a_dead_service_left_running(db_path, host, monkeypatch):
    monkeypatch.setattr(IndexRunner, "is_running", staticmethod(lambda *a, **k: (False, None)))
    job = IndexJobs.enqueue(None, db_path=db_path)
    IndexJobs.claim_next(db_path)
    host.stop()

    host.run()

    assert IndexJobs.get(job.id, db_path).status == "queued"
