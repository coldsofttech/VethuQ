from typer.testing import CliRunner
from vethuq_cli.db import IntegrityCheck
from vethuq_cli.main import app
from vethuq_core.db.backup import Backup
from vethuq_core.db.integrity import IntegrityCheckResult
from vethuq_core.index.runner import IndexRunner
from vethuq_core.storage import open_storage

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


class TestBackupCommands:
    def test_create_list_and_delete(self, use_temp_db):
        use_temp_db()
        open_storage().close()

        created = runner.invoke(app, ["db", "backup", "create", "mine"])
        listed = runner.invoke(app, ["db", "backup", "list"])
        deleted = runner.invoke(app, ["db", "backup", "delete", "mine", "--force"])

        assert created.exit_code == 0
        assert "mine" in created.stdout
        assert "mine" in listed.stdout
        assert deleted.exit_code == 0
        assert "mine" not in [b.name for b in Backup.entries(use_temp_db())]

    def test_create_rejects_a_bad_name(self, use_temp_db):
        use_temp_db()
        open_storage().close()

        result = runner.invoke(app, ["db", "backup", "create", "bad name"])

        assert result.exit_code == 1

    def test_delete_asks_first_and_aborts_on_no(self, use_temp_db):
        db_path = use_temp_db()
        open_storage().close()
        Backup.create(db_path, "keep")

        result = runner.invoke(app, ["db", "backup", "delete", "keep"], input="n\n")

        assert "Aborted" in result.stdout
        assert "keep" in [b.name for b in Backup.entries(db_path)]


class TestRestoreResetRepair:
    def test_restore_replaces_database_and_keeps_safety_copy(self, use_temp_db):
        db_path = use_temp_db()
        open_storage().close()
        Backup.create(db_path, "good")

        result = runner.invoke(app, ["db", "restore", "good", "--force"])

        assert result.exit_code == 0
        assert "restored" in result.stdout
        assert any(b.kind == "safety" for b in Backup.entries(db_path))

    def test_restore_aborts_without_confirmation(self, use_temp_db):
        db_path = use_temp_db()
        open_storage().close()
        Backup.create(db_path, "good")

        result = runner.invoke(app, ["db", "restore", "good"], input="n\n")

        assert "Aborted" in result.stdout
        assert not any(b.kind == "safety" for b in Backup.entries(db_path))

    def test_restore_unknown_backup_fails(self, use_temp_db):
        use_temp_db()
        open_storage().close()

        result = runner.invoke(app, ["db", "restore", "nope", "--force"])

        assert result.exit_code == 1

    def test_reset_clears_the_database(self, use_temp_db):
        db_path = use_temp_db()
        open_storage().close()

        result = runner.invoke(app, ["db", "reset", "--force"])

        assert result.exit_code == 0
        assert not db_path.exists()

    def test_repair_passes_on_a_healthy_database(self, use_temp_db):
        use_temp_db()
        open_storage().close()

        result = runner.invoke(app, ["db", "repair"])

        assert result.exit_code == 0
        assert "repaired" in result.stdout

    def test_repair_failure_points_to_restore_and_reset(self, use_temp_db, monkeypatch):
        use_temp_db()
        open_storage().close()
        monkeypatch.setattr(
            Backup,
            "repair",
            staticmethod(lambda p: (IntegrityCheckResult(ok=False, errors=["bad"]), None)),
        )

        result = runner.invoke(app, ["db", "repair"])

        assert result.exit_code == 1
        assert "db restore" in result.output
        assert "db reset" in result.output

    def test_refuses_while_an_index_run_is_active(self, use_temp_db, monkeypatch):
        use_temp_db()
        open_storage().close()
        monkeypatch.setattr(IndexRunner, "is_running", staticmethod(lambda p: (True, 1)))

        for args in (["restore", "x", "--force"], ["reset", "--force"], ["repair"]):
            result = runner.invoke(app, ["db", *args])
            assert result.exit_code == 1
            assert "index run is in progress" in result.output
