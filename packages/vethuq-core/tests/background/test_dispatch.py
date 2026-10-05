import pytest
from vethuq_core.background import (
    BackgroundService,
    Dispatch,
    IndexJobs,
    ServiceState,
    ServiceStatus,
)
from vethuq_core.index import IndexRunner, IndexRunnerError
from vethuq_core.sources import SourceNotFoundError, Sources
from vethuq_core.storage import open_storage


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
        return 4321

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(fake_start_run))
    return calls


def test_without_the_service_the_run_starts_directly(db_path, started, monkeypatch):
    _service(monkeypatch, None)

    result = Dispatch.submit(None, restart=True, languages="te", db_path=db_path)

    assert (result.pid, result.queued) == (4321, False)
    assert started[0][1]["restart"] is True
    assert started[0][1]["languages"] == "te"
    assert IndexJobs.queued(db_path) == []


def test_with_the_service_the_run_is_queued_not_started(db_path, source_id, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    result = Dispatch.submit(str(source_id), languages="en", db_path=db_path)

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

    result = Dispatch.submit(None, db_path=db_path)

    assert result.queued and result.service_idle


def test_one_off_ignores_the_service(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    result = Dispatch.submit(None, via=Dispatch.VIA_ONE_OFF, db_path=db_path)

    assert result.pid == 4321 and not result.queued
    assert IndexJobs.queued(db_path) == []


def test_a_bad_source_is_refused_before_it_is_queued(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    with pytest.raises(SourceNotFoundError):
        Dispatch.submit("999", db_path=db_path)

    assert IndexJobs.queued(db_path) == []


def test_asking_for_the_service_when_it_is_not_installed_is_an_error(db_path, started, monkeypatch):
    _service(monkeypatch, None)

    with pytest.raises(IndexRunnerError, match="isn't installed"):
        Dispatch.submit(None, via=Dispatch.VIA_SERVICE, db_path=db_path)


def test_repeated_requests_share_one_queued_job(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING)

    first = Dispatch.submit(None, db_path=db_path)
    second = Dispatch.submit(None, db_path=db_path)

    assert first.job_id == second.job_id


def test_a_service_for_another_data_folder_is_not_used(db_path, started, tmp_path, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING, home=tmp_path / "someone-else")

    result = Dispatch.submit(None, db_path=db_path)

    assert result.pid == 4321 and not result.queued
    assert IndexJobs.queued(db_path) == []


def test_a_service_for_this_data_folder_is_used(db_path, started, monkeypatch):
    _service(monkeypatch, ServiceState.RUNNING, home=db_path.parent)

    result = Dispatch.submit(None, db_path=db_path)

    assert result.queued
