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


class TestInstallCredentials:
    @pytest.fixture
    def seen(self, monkeypatch):
        seen = {}
        status = _service(monkeypatch, ServiceState.RUNNING)
        monkeypatch.setattr(BackgroundService, "backend", staticmethod(lambda: "windows"))
        monkeypatch.setattr(BackgroundService, "current_account", staticmethod(lambda: r"PC\me"))
        monkeypatch.setattr(
            BackgroundService,
            "perform",
            staticmethod(lambda a, **kwargs: seen.update(kwargs) or status),
        )
        return seen

    def test_it_asks_which_account_with_the_current_user_as_the_default(self, monkeypatch, seen):
        from vethuq_cli import background

        asked = {}
        monkeypatch.setattr(background, "_is_interactive", lambda: True)
        monkeypatch.setattr(
            background.Prompt,
            "ask",
            staticmethod(lambda *a, **k: asked.update(k) or r"PC\svc"),
        )

        runner.invoke(app, ["background-service", "install"])

        assert asked["default"] == r"PC\me"
        assert seen["account"] == r"PC\svc" and seen["system"] is False

    def test_without_a_terminal_it_uses_the_current_user(self, seen):
        runner.invoke(app, ["background-service", "install"])

        assert seen["account"] == r"PC\me"

    def test_an_account_given_is_not_asked_for_again(self, monkeypatch, seen):
        from vethuq_cli import background

        monkeypatch.setattr(background, "_is_interactive", lambda: True)
        monkeypatch.setattr(
            background.Prompt, "ask", staticmethod(lambda *a, **k: pytest.fail("asked"))
        )

        runner.invoke(app, ["background-service", "install", "--account", r"PC\svc"])

        assert seen["account"] == r"PC\svc"

    def test_system_asks_for_no_account(self, monkeypatch, seen):
        from vethuq_cli import background

        monkeypatch.setattr(background, "_is_interactive", lambda: True)
        monkeypatch.setattr(
            background.Prompt, "ask", staticmethod(lambda *a, **k: pytest.fail("asked"))
        )

        runner.invoke(app, ["background-service", "install", "--system"])

        assert seen["system"] is True and seen["account"] is None

    def test_the_data_folder_can_be_chosen(self, seen, tmp_path):
        runner.invoke(app, ["background-service", "install", "--home", str(tmp_path)])

        assert seen["home"] == tmp_path


class TestQueue:
    def _jobs(self):
        first = IndexJobs.enqueue("1")
        IndexJobs.claim_next()
        second = IndexJobs.enqueue(None, restart=True, languages="en")
        done = IndexJobs.enqueue("9")
        IndexJobs.cancel_queued()
        IndexJobs.finish(first.id, "failed", "boom")
        return first, second, done

    def test_list_shows_pending_jobs_only(self, use_temp_db):
        use_temp_db()
        IndexJobs.enqueue("1")
        IndexJobs.claim_next()
        IndexJobs.enqueue("2")
        finished = IndexJobs.enqueue("3")
        IndexJobs.claim_next()  # job 2 runs after 1 is done; simulate by finishing 1 and 2
        IndexJobs.finish(1, "completed")
        IndexJobs.finish(2, "completed")

        result = runner.invoke(app, ["background-service", "queue", "list", "--json"])

        assert [j["id"] for j in json.loads(result.output)] == [finished.id]

    def test_list_all_includes_finished_jobs(self, use_temp_db):
        use_temp_db()
        first, second, done = self._jobs()

        result = runner.invoke(app, ["background-service", "queue", "list", "--all", "--json"])

        assert {j["id"] for j in json.loads(result.output)} == {first.id, second.id, done.id}

    def test_an_empty_queue_says_so(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["background-service", "queue", "list"])

        assert result.exit_code == 0
        assert "The queue is empty" in result.output

    def test_list_table(self, use_temp_db):
        use_temp_db()
        IndexJobs.enqueue(None, restart=True, languages="en")

        result = runner.invoke(app, ["background-service", "queue", "list"])

        assert "all sources" in result.output and "restart" in result.output
        assert "queued" in result.output

    def test_show_describes_one_job(self, use_temp_db):
        use_temp_db()
        first, _, _ = self._jobs()

        result = runner.invoke(app, ["background-service", "queue", "show", str(first.id)])

        assert result.exit_code == 0
        assert "failed" in result.output and "boom" in result.output
        assert "Target: 1" in result.output

    def test_show_json(self, use_temp_db):
        use_temp_db()
        job = IndexJobs.enqueue("4", languages="te")

        result = runner.invoke(app, ["background-service", "queue", "show", str(job.id), "--json"])

        data = json.loads(result.output)
        assert (data["target"], data["languages"], data["status"]) == ("4", "te", "queued")

    def test_show_an_unknown_job_is_an_error(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["background-service", "queue", "show", "99"])

        assert result.exit_code == 1
        assert "No queued job has id 99" in result.output


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
