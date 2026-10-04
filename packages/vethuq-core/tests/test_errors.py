import sys
import types

import pytest
from vethuq_core.db import Db
from vethuq_core.errors import (
    CorruptDatabaseError,
    DataFolderNotWritableError,
    InvalidConfigError,
    OcrModelMissingError,
    SchemaVersionError,
    StaleLockError,
    StartupError,
)
from vethuq_core.paths import Paths


class TestStartupError:
    def test_str_joins_message_and_hint(self):
        err = StartupError("Something broke.", "Try again.")

        assert str(err) == "Something broke. Try again."

    def test_str_is_just_the_message_without_a_hint(self):
        assert str(StartupError("Something broke.")) == "Something broke."

    def test_every_error_has_a_distinct_non_zero_exit_code(self):
        codes = [
            cls.exit_code
            for cls in (
                InvalidConfigError,
                DataFolderNotWritableError,
                CorruptDatabaseError,
                OcrModelMissingError,
                SchemaVersionError,
                StaleLockError,
            )
        ]

        assert all(code != 0 for code in codes)
        assert len(set(codes)) == len(codes)


class TestInvalidConfig:
    @pytest.fixture
    def config_file(self, tmp_path, monkeypatch):
        file = tmp_path / "config" / "location.json"
        file.parent.mkdir()
        monkeypatch.setattr(Paths, "location_file", staticmethod(lambda: file))
        monkeypatch.delenv(Paths.ENV_VAR, raising=False)
        return file

    def test_malformed_settings_file_is_reported(self, config_file):
        config_file.write_text("{not json", encoding="utf-8")

        with pytest.raises(InvalidConfigError) as excinfo:
            Paths.check_config()

        assert str(config_file) in excinfo.value.message
        assert "delete" in excinfo.value.hint.lower()

    def test_settings_file_that_is_not_an_object_is_reported(self, config_file):
        config_file.write_text("[1, 2]", encoding="utf-8")

        with pytest.raises(InvalidConfigError):
            Paths.check_config()

    def test_env_var_pointing_at_a_file_is_reported(self, config_file, tmp_path, monkeypatch):
        a_file = tmp_path / "file.txt"
        a_file.write_text("x")
        monkeypatch.setenv(Paths.ENV_VAR, str(a_file))

        with pytest.raises(InvalidConfigError) as excinfo:
            Paths.check_config()

        assert Paths.ENV_VAR in excinfo.value.message

    def test_valid_or_missing_config_passes(self, config_file):
        Paths.check_config()
        config_file.write_text('{"location": "x"}', encoding="utf-8")
        Paths.check_config()

    def test_default_db_path_surfaces_the_config_error(self, config_file):
        config_file.write_text("{not json", encoding="utf-8")

        with pytest.raises(InvalidConfigError):
            Db.default_db_path()


class TestDataFolderNotWritable:
    def test_folder_that_cannot_be_created_is_reported(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("x")

        with pytest.raises(DataFolderNotWritableError) as excinfo:
            Paths.ensure_writable(blocker / "db")

        assert str(blocker / "db") in excinfo.value.message
        assert "permissions" in excinfo.value.hint

    def test_folder_that_rejects_writes_is_reported(self, tmp_path, monkeypatch):
        def deny(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr("tempfile.TemporaryFile", deny)

        with pytest.raises(DataFolderNotWritableError):
            Paths.ensure_writable(tmp_path / "db")

    def test_writable_folder_is_created_and_left_clean(self, tmp_path):
        Paths.ensure_writable(tmp_path / "db")

        assert (tmp_path / "db").is_dir()
        assert list((tmp_path / "db").iterdir()) == []


class TestCorruptDatabase:
    def test_file_that_is_not_a_database_is_reported(self, tmp_path):
        db_path = tmp_path / "vethuq.db"
        db_path.write_bytes(b"this is definitely not a sqlite database" * 50)

        with pytest.raises(CorruptDatabaseError) as excinfo:
            Db.connect(db_path)

        assert str(db_path) in excinfo.value.message
        assert "vethuq db restore" in excinfo.value.hint

    def test_locked_database_is_not_reported_as_corrupt(self):
        import sqlite3

        assert Db._corruption_error(sqlite3.OperationalError("database is locked"), None) is None


class TestOcrModelMissing:
    def test_missing_engine_package_is_reported(self, monkeypatch):
        from vethuq_core.ocr.engines.paddle import PaddleOcrEngine

        monkeypatch.setitem(sys.modules, "paddleocr", None)

        with pytest.raises(OcrModelMissingError) as excinfo:
            PaddleOcrEngine()

        assert "isn't installed" in excinfo.value.message

    def test_model_load_failure_is_reported(self, monkeypatch):
        from vethuq_core.ocr.engines.paddle import PaddleOcrEngine

        def broken(**kwargs):
            raise RuntimeError("model files not found")

        fake = types.ModuleType("paddleocr")
        fake.PaddleOCR = broken
        monkeypatch.setitem(sys.modules, "paddleocr", fake)
        monkeypatch.setattr(PaddleOcrEngine, "resolve_device", staticmethod(lambda use_gpu: "cpu"))

        with pytest.raises(OcrModelMissingError) as excinfo:
            PaddleOcrEngine()

        assert "model files not found" in excinfo.value.message

    def test_check_installed_reports_a_missing_engine(self, monkeypatch):
        from vethuq_core.ocr.engines import paddle

        monkeypatch.setattr(paddle, "find_spec", lambda name: None)

        with pytest.raises(OcrModelMissingError):
            paddle.PaddleOcrEngine.check_installed()

    def test_check_installed_is_skipped_in_the_frozen_build(self, monkeypatch):
        import sys

        from vethuq_core.ocr.engines import paddle

        # The UI/CLI exes don't bundle the engine (only the worker does), so they can't see it.
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(paddle, "find_spec", lambda name: None)

        paddle.PaddleOcrEngine.check_installed()

    def test_start_run_fails_fast_when_the_engine_is_missing(self, tmp_path, monkeypatch):
        from vethuq_core.index import IndexRunner
        from vethuq_core.ocr.engines import paddle

        monkeypatch.setattr(paddle, "find_spec", lambda name: None)
        launched = []
        monkeypatch.setattr("subprocess.Popen", lambda *a, **k: launched.append(a))

        with pytest.raises(OcrModelMissingError):
            IndexRunner.start_run(db_path=tmp_path / "vethuq.db")

        assert launched == []
