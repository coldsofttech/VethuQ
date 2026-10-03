import sqlite3

import pytest
import vethuq_cli.main as main_module
from vethuq_core.db import Db
from vethuq_core.errors import SchemaVersionError


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

        assert excinfo.value.code == SchemaVersionError.exit_code
        err = capsys.readouterr().err
        assert "newer" in err
        assert "Traceback" not in err


class TestStartupErrors:
    def test_invalid_config_exits_with_its_code_and_a_plain_message(
        self, tmp_path, monkeypatch, capsys
    ):
        from vethuq_core.errors import InvalidConfigError
        from vethuq_core.paths import Paths

        bad = tmp_path / "location.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(Paths, "location_file", staticmethod(lambda: bad))
        monkeypatch.delenv(Paths.ENV_VAR, raising=False)
        monkeypatch.setattr("sys.argv", ["vethuq", "source", "list"])

        with pytest.raises(SystemExit) as excinfo:
            main_module.Cli.run()

        assert excinfo.value.code == InvalidConfigError.exit_code
        err = capsys.readouterr().err
        assert "Error:" in err
        assert "What to do:" in err
        assert "Traceback" not in err

    def test_corrupt_database_exits_with_its_code(self, use_temp_db, monkeypatch, capsys):
        from vethuq_core.errors import CorruptDatabaseError

        db_path = use_temp_db()
        db_path.write_bytes(b"not a database at all" * 100)
        monkeypatch.setattr("sys.argv", ["vethuq", "source", "list"])

        with pytest.raises(SystemExit) as excinfo:
            main_module.Cli.run()

        assert excinfo.value.code == CorruptDatabaseError.exit_code
        assert "What to do:" in capsys.readouterr().err

    def test_startup_error_is_logged(self, monkeypatch, caplog):
        from vethuq_core.errors import OcrModelMissingError

        def boom():
            raise OcrModelMissingError("No models.", "Reinstall.")

        monkeypatch.setattr(main_module, "app", boom)

        with caplog.at_level("ERROR"), pytest.raises(SystemExit) as excinfo:
            main_module.Cli.run()

        assert excinfo.value.code == OcrModelMissingError.exit_code
        assert "No models." in caplog.text


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
