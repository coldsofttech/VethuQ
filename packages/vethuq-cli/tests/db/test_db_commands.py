from typer.testing import CliRunner
from vethuq_cli.db import IntegrityCheck
from vethuq_cli.main import app
from vethuq_core.db.integrity import IntegrityCheckResult

runner = CliRunner()


class TestIntegrityCheck:
    def test_passes_on_a_healthy_database(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["db", "integrity-check"])

        assert result.exit_code == 0
        assert "passed" in result.stdout

    def test_reports_failure(self, use_temp_db, monkeypatch):
        use_temp_db()
        monkeypatch.setattr(
            IntegrityCheck,
            "run",
            staticmethod(
                lambda _conn: IntegrityCheckResult(ok=False, errors=["row 3 missing from index x"])
            ),
        )

        result = runner.invoke(app, ["db", "integrity-check"])

        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "row 3 missing from index x" in result.output
