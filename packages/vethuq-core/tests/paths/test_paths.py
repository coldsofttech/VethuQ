import json
from pathlib import Path

import pytest
from vethuq_core.db import Db
from vethuq_core.paths import Paths


class TestPaths:
    def test_data_root_of_db_in_db_folder_is_its_parent(self, tmp_path):
        assert Paths.data_root(tmp_path / "db" / "vethuq.db") == tmp_path

    def test_data_root_of_db_elsewhere_is_its_own_dir(self, tmp_path):
        assert Paths.data_root(tmp_path / "vethuq.db") == tmp_path

    def test_run_and_logs_dirs_are_created_next_to_db_folder(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"

        assert Paths.run_dir(db_path) == tmp_path / "run"
        assert Paths.logs_dir(db_path) == tmp_path / "logs"
        assert (tmp_path / "run").is_dir()
        assert (tmp_path / "logs").is_dir()

    def test_default_db_path_lives_in_db_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: tmp_path))

        path = Db.default_db_path()

        assert path == tmp_path / "db" / "vethuq.db"
        assert path.parent.is_dir()

    def test_default_db_path_migrates_legacy_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: tmp_path))
        (tmp_path / "vethuq.db").write_text("data")
        (tmp_path / "vethuq.db-wal").write_text("wal")

        path = Db.default_db_path()

        assert path.read_text() == "data"
        assert (path.parent / "vethuq.db-wal").read_text() == "wal"
        assert not (tmp_path / "vethuq.db").exists()

    def test_default_db_path_does_not_overwrite_existing_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: tmp_path))
        (tmp_path / "db").mkdir()
        (tmp_path / "db" / "vethuq.db").write_text("new")
        (tmp_path / "vethuq.db").write_text("old")

        Db.default_db_path()

        assert Path(tmp_path / "db" / "vethuq.db").read_text() == "new"
        assert (tmp_path / "vethuq.db").read_text() == "old"


class TestLocation:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.delenv(Paths.ENV_VAR, raising=False)
        monkeypatch.setattr(
            Paths, "location_file", staticmethod(lambda: tmp_path / "cfg" / "location.json")
        )
        monkeypatch.setattr(Paths, "platform_data_root", staticmethod(lambda: tmp_path / "default"))

    def test_precedence_env_then_file_then_default(self, tmp_path, monkeypatch):
        assert Paths.resolve_data_root() == tmp_path / "default"
        Paths.save_location(tmp_path / "saved")
        assert Paths.resolve_data_root() == tmp_path / "saved"
        monkeypatch.setenv(Paths.ENV_VAR, str(tmp_path / "env"))
        assert Paths.resolve_data_root() == tmp_path / "env"

    def test_pointer_file_stores_only_the_location(self, tmp_path):
        Paths.save_location(tmp_path / "saved")
        assert list(json.loads(Paths.location_file().read_text())) == [Paths.LOCATION_KEY]

    def test_move_data_moves_folders_and_repoints(self, tmp_path):
        src, dst = tmp_path / "default", tmp_path / "new"
        for name in ("db", "run", "logs"):
            (src / name).mkdir(parents=True)
            (src / name / "f.txt").write_text(name)
        Paths.move_data(src, dst)
        assert (dst / "db" / "f.txt").read_text() == "db"
        assert not (src / "db").exists()
        assert Paths.resolve_data_root() == dst

    def test_plan_move_refuses_nested_and_populated_targets(self, tmp_path):
        src = tmp_path / "default"
        (src / "db").mkdir(parents=True)
        with pytest.raises(ValueError):
            Paths.plan_move(src, src / "inner")
        (tmp_path / "new" / "db").mkdir(parents=True)
        (tmp_path / "new" / "db" / "x").write_text("x")
        with pytest.raises(ValueError):
            Paths.plan_move(src, tmp_path / "new")
