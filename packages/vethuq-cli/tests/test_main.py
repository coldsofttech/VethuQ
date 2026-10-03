import sqlite3

import pytest
import vethuq_cli.main as main_module
from vethuq_core.db import Db


class TestCliRun:
    def test_reports_newer_database_schema_cleanly(self, use_temp_db, monkeypatch, capsys):
        db_path = use_temp_db()
        newer = sqlite3.connect(db_path)
        newer.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        newer.execute("INSERT INTO schema_version (version) VALUES (?)", (Db.SCHEMA_VERSION + 1,))
        newer.commit()
        newer.close()
        monkeypatch.setattr("sys.argv", ["vethuq", "source", "list"])

        with pytest.raises(SystemExit) as excinfo:
            main_module.Cli.run()

        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "newer" in err
        assert "Traceback" not in err


class TestVersionOption:
    def test_prints_cli_python_platform_and_schema(self, use_temp_db):
        from typer.testing import CliRunner

        use_temp_db()
        result = CliRunner().invoke(main_module.app, ["--version"])

        assert result.exit_code == 0
        assert "VethuQ CLI" in result.stdout
        assert "Python " in result.stdout
        assert "Platform " in result.stdout
        assert "Database schema" in result.stdout
        assert str(Db.SCHEMA_VERSION) in result.stdout
        assert "Version" in result.stdout
