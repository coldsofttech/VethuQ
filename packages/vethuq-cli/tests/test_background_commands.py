import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.index import commands as index_commands
from vethuq_cli.main import app
from vethuq_core.background import (
    BackgroundService,
    BackgroundServiceError,
    IndexJobs,
    ServiceState,
    ServiceStatus,
)
from vethuq_core.index import IndexRunner
from vethuq_core.sources import Sources
from vethuq_core.storage import open_storage

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide(monkeypatch):
    monkeypatch.setattr(console, "width", 200)


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "docs"
    path.mkdir()
    return path


def _service(monkeypatch, state):
    """The service as installed in `state`, or not installed when `state` is None."""
    status = ServiceStatus(
        True, state is not None, state or ServiceState.NOT_INSTALLED, "windows", "VethuQBackground"
    )
    monkeypatch.setattr(BackgroundService, "status", staticmethod(lambda: status))
    return status


class TestControlCommands:
    @pytest.mark.parametrize(
        "action", ["install", "uninstall", "start", "stop", "restart", "pause", "resume"]
    )
    def test_each_command_performs_its_action(self, monkeypatch, action):
        status = _service(monkeypatch, ServiceState.RUNNING)
        done = []
        monkeypatch.setattr(
            BackgroundService,
            "perform",
            staticmethod(lambda a, **kwargs: done.append(a) or status),
        )

        result = runner.invoke(app, ["background-service", action])

        assert result.exit_code == 0, result.output
        assert done == [action]

    def test_install_can_name_the_account(self, monkeypatch):
        status = _service(monkeypatch, ServiceState.RUNNING)
        seen = {}
        monkeypatch.setattr(
            BackgroundService,
            "perform",
            staticmethod(lambda a, **kwargs: seen.update(kwargs) or status),
        )

        runner.invoke(app, ["background-service", "install", "--account", r"PC\me"])

        assert seen["account"] == r"PC\me"

    def test_a_refused_action_is_reported_with_exit_code_1(self, monkeypatch):
        def perform(action, **kwargs):
            raise BackgroundServiceError("The background service isn't installed.")

        monkeypatch.setattr(BackgroundService, "perform", staticmethod(perform))

        result = runner.invoke(app, ["background-service", "stop"])

        assert result.exit_code == 1
        assert "isn't installed" in result.output


class TestStatus:
    def test_not_installed(self, monkeypatch):
        _service(monkeypatch, None)

        result = runner.invoke(app, ["background-service", "status"])

        assert result.exit_code == 0
        assert "not installed" in result.output
        assert "background-service install" in result.output

    def test_json_lists_the_service_and_queue(self, monkeypatch, use_temp_db):
        use_temp_db()
        _service(monkeypatch, ServiceState.PAUSED)
        IndexJobs.enqueue("3")

        result = runner.invoke(app, ["background-service", "status", "--json"])

        data = json.loads(result.output)
        assert data["service"]["state"] == "paused"
        assert [job["target"] for job in data["queued"]] == ["3"]

    def test_text_shows_queued_jobs(self, monkeypatch, use_temp_db):
        use_temp_db()
        _service(monkeypatch, ServiceState.RUNNING)
        IndexJobs.enqueue(None, restart=True)

        result = runner.invoke(app, ["background-service", "status"])

        assert "Queued jobs: 1" in result.output
        assert "all sources" in result.output


class TestIndexCommandsUseTheService:
    @pytest.fixture
    def source(self, use_temp_db, folder):
        use_temp_db()
        runner.invoke(app, ["source", "add", str(folder)])
        storage = open_storage()
        try:
            return str(Sources.get(storage, str(folder)).id)
        finally:
            storage.close()

    @pytest.fixture
    def started(self):
        with patch.object(IndexRunner, "start_run", return_value=4321) as start:
            yield start

    def test_run_is_queued_when_the_service_is_installed(self, monkeypatch, source, started):
        _service(monkeypatch, ServiceState.RUNNING)

        result = runner.invoke(app, ["index", "run", source, "--lang", "en"])

        assert result.exit_code == 0, result.output
        started.assert_not_called()
        job = IndexJobs.queued()[0]
        assert (job.target, job.mode, job.languages) == (source, "run", "en")
        assert "Queued index run for the background service" in result.output

    def test_restart_is_queued_as_a_restart(self, monkeypatch, source, started):
        _service(monkeypatch, ServiceState.RUNNING)

        runner.invoke(app, ["index", "restart", source])

        assert IndexJobs.queued()[0].mode == "restart"
        started.assert_not_called()

    def test_reindex_is_queued(self, monkeypatch, source, started):
        _service(monkeypatch, ServiceState.RUNNING)

        result = runner.invoke(app, ["index", "reindex", source, "--force"])

        assert result.exit_code == 0, result.output
        started.assert_not_called()
        assert IndexJobs.queued()[0].target == source

    def test_one_off_runs_a_worker_even_with_the_service(self, monkeypatch, source, started):
        _service(monkeypatch, ServiceState.RUNNING)

        result = runner.invoke(app, ["index", "run", source, "--one-off"])

        assert result.exit_code == 0, result.output
        started.assert_called_once()
        assert IndexJobs.queued() == []

    def test_without_the_service_a_worker_starts_as_before(self, monkeypatch, source, started):
        _service(monkeypatch, None)

        result = runner.invoke(app, ["index", "run", source])

        assert result.exit_code == 0, result.output
        started.assert_called_once()

    def test_a_stopped_service_without_a_terminal_queues_and_warns(
        self, monkeypatch, source, started
    ):
        _service(monkeypatch, ServiceState.STOPPED)

        result = runner.invoke(app, ["index", "run", source])

        assert result.exit_code == 0, result.output
        started.assert_not_called()
        assert len(IndexJobs.queued()) == 1
        assert "The service is stopped" in result.output

    @pytest.mark.parametrize(("answer", "queued"), [("queue", True), ("one-off", False)])
    def test_a_stopped_service_with_a_terminal_asks(
        self, monkeypatch, source, started, answer, queued
    ):
        _service(monkeypatch, ServiceState.PAUSED)
        monkeypatch.setattr(index_commands, "_is_interactive", lambda: True)
        monkeypatch.setattr(index_commands.Prompt, "ask", staticmethod(lambda *a, **k: answer))

        result = runner.invoke(app, ["index", "run", source])

        assert result.exit_code == 0, result.output
        assert bool(IndexJobs.queued()) is queued
        assert started.called is (not queued)

    def test_an_unknown_source_is_refused_without_queueing(self, monkeypatch, source, started):
        _service(monkeypatch, ServiceState.RUNNING)

        result = runner.invoke(app, ["index", "run", "999"])

        assert result.exit_code == 1
        assert IndexJobs.queued() == []
