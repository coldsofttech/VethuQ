import pytest
import vethuq_cli.main as main_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.policy import PolicyService

runner = CliRunner()


@pytest.fixture(autouse=True)
def _fresh_policy_service(use_temp_db):
    use_temp_db()
    PolicyService.reset()
    yield
    PolicyService.reset()


class TestPolicyCommand:
    def test_show_reports_the_baseline_when_nothing_was_fetched(self):
        result = runner.invoke(app, ["policy", "show"])

        assert result.exit_code == 0, result.output
        assert "built-in baseline" in result.output
        assert "0.0.0" in result.output

    def test_refresh_without_embedded_keys_makes_no_request_and_reports_it(self):
        result = runner.invoke(app, ["policy", "refresh"])

        assert result.exit_code == 0, result.output
        assert "skipped" in result.output
        assert "no policy keys" in result.output


class TestStartup:
    def test_every_command_starts_the_policy_refresh_in_the_background(self, monkeypatch):
        started = []
        monkeypatch.setattr(
            PolicyService, "start", staticmethod(lambda logger=None: started.append(logger))
        )

        result = runner.invoke(app, ["policy", "show"])

        assert result.exit_code == 0, result.output
        assert started == [main_module._logger]

    def test_a_policy_failure_never_stops_a_command(self, monkeypatch):
        from vethuq_core.policy import PolicyClient

        def boom(self, force=False):
            raise RuntimeError("no threads")

        monkeypatch.setattr(PolicyClient, "refresh_in_background", boom)

        result = runner.invoke(app, ["policy", "show"])

        assert result.exit_code == 0, result.output
