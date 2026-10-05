import pytest
from vethuq_core.background import BackgroundService, ServiceState, ServiceStatus
from vethuq_core.index import Indexing, IndexJobs, IndexRunner, IndexRunnerError
from vethuq_core.sources import SourceNotFoundError, Sources
from vethuq_core.storage import open_storage


@pytest.fixture(autouse=True)
def _workers_are_alive(monkeypatch):
    """The pids these tests use belong to no process; count them as running workers."""
    monkeypatch.setattr(IndexRunner, "_is_pid_running", staticmethod(lambda pid: True))


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vethuq.db"


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "docs"
    path.mkdir()
    return path


@pytest.fixture
def source_id(db_path, folder):
    storage = open_storage(db_path)
    try:
        return Sources.add(storage, folder).id
    finally:
        storage.close()


def _service(monkeypatch, state=None, home=None):
    """Pretend the service is installed in `state`, or not installed when `state` is None."""
    status = ServiceStatus(
        True,
        state is not None,
        state or ServiceState.NOT_INSTALLED,
        "windows",
        "VethuQBackground",
        home=str(home) if home is not None else None,
    )
    monkeypatch.setattr(BackgroundService, "status", staticmethod(lambda: status))


@pytest.fixture
def started(monkeypatch):
    calls = []

    def fake_start_run(target=None, **kwargs):
        calls.append((target, kwargs))
        # what the real one does once it has launched the worker
        IndexJobs.mark_started(kwargs["job_id"], 4321, kwargs["db_path"])
        return 4321

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(fake_start_run))
    return calls


def test_without_the_service_the_run_starts_directly(db_path, started, monkeypatch):
    _service(monkeypatch, None)

    result = Indexing.submit(None, restart=True, languages="en", db_path=db_path)

    assert (result.pid, result.queued) == (4321, False)
    assert started[0][1]["restart"] is True
    assert started[0][1]["languages"] == "en"
    assert IndexJobs.queued(db_path) == []


def test_a_one_off_request_is_recorded_as_a_running_job(db_path, started, monkeypatch):
    _service(monkeypatch, None)

    result = Indexing.submit(None, db_path=db_path)

    job = IndexJobs.get(result.job_id, db_path)
    assert (job.status, job.pid, job.mode) == ("running", 4321, "run")
    assert started[0][1]["job_id"] == result.job_id
    assert result.queued is False


def test_a_one_off_that_cannot_start_leaves_a_failed_job_with_the_reason(db_path, monkeypatch):
    from vethuq_core.index import AlreadyRunningError

    _service(monkeypatch, None)

    def refuse(target=None, **kwargs):
        raise AlreadyRunningError("An index run is already in progress (pid 99).")

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(refuse))

    with pytest.raises(AlreadyRunningError):
        Indexing.submit(None, db_path=db_path)

    (job,) = IndexJobs.list(None, db_path=db_path)
    assert job.status == "failed"
    assert "already in progress" in job.error


def test_a_build_without_the_service_package_always_runs_a_one_off(db_path, started, monkeypatch):
    monkeypatch.setattr(Indexing, "has_service", staticmethod(lambda: False))
    _service(monkeypatch, ServiceState.RUNNING)

    result = Indexing.submit(None, db_path=db_path)

    assert result.pid == 4321 and not result.queued
    assert IndexJobs.get(result.job_id, db_path).status == "running"


def test_a_bad_request_leaves_no_job_behind(db_path, started, monkeypatch):
    _service(monkeypatch, None)

    with pytest.raises(SourceNotFoundError):
        Indexing.submit("999", db_path=db_path)

    assert IndexJobs.list(None, db_path=db_path) == []


def test_with_the_service_the_run_is_queued_not_started(db_path, source_id, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    result = Indexing.submit(str(source_id), languages="en", db_path=db_path)

    assert result.queued and result.pid is None
    assert started == []
    job = IndexJobs.queued(db_path)[0]
    assert (job.id, job.target, job.languages) == (result.job_id, str(source_id), "en")
    assert result.service_idle is False


@pytest.mark.parametrize("state", [ServiceState.STOPPED, ServiceState.PAUSED])
def test_a_queued_job_notes_when_the_service_is_not_taking_jobs(
    db_path, started, monkeypatch, state
):
    _service(monkeypatch, state)

    result = Indexing.submit(None, db_path=db_path)

    assert result.queued and result.service_idle


def test_one_off_ignores_the_service(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    result = Indexing.submit(None, via=Indexing.VIA_ONE_OFF, db_path=db_path)

    assert result.pid == 4321 and not result.queued
    assert IndexJobs.queued(db_path) == []


def test_a_bad_source_is_refused_before_it_is_queued(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    with pytest.raises(SourceNotFoundError):
        Indexing.submit("999", db_path=db_path)

    assert IndexJobs.queued(db_path) == []


def test_asking_for_the_service_when_it_is_not_installed_is_an_error(db_path, started, monkeypatch):
    _service(monkeypatch, None)

    with pytest.raises(IndexRunnerError, match="isn't installed"):
        Indexing.submit(None, via=Indexing.VIA_SERVICE, db_path=db_path)


def test_repeated_requests_share_one_queued_job(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    first = Indexing.submit(None, db_path=db_path)
    second = Indexing.submit(None, db_path=db_path)

    assert first.job_id == second.job_id


def test_a_service_for_another_data_folder_is_not_used(db_path, started, tmp_path, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING, home=tmp_path / "someone-else")

    result = Indexing.submit(None, db_path=db_path)

    assert result.pid == 4321 and not result.queued
    assert IndexJobs.queued(db_path) == []


def test_a_service_for_this_data_folder_is_used(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING, home=db_path.parent)

    result = Indexing.submit(None, db_path=db_path)

    assert result.queued
