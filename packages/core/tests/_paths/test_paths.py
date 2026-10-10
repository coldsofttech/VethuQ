from __future__ import annotations

import json

import pytest

import vethuq
from vethuq import paths
from vethuq._paths import _Paths


class TestInternalPaths:
    def test_data_root_of_db_in_db_folder_is_its_parent(self, tmp_path):
        assert _Paths.data_root(tmp_path / "db" / "vethuq.db") == tmp_path

    def test_data_root_of_db_elsewhere_is_its_own_dir(self, tmp_path):
        assert _Paths.data_root(tmp_path / "vethuq.db") == tmp_path

    def test_run_and_logs_dirs_are_created_next_to_db_folder(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"

        assert _Paths.run_dir(db_path) == tmp_path / "run"
        assert _Paths.logs_dir(db_path) == tmp_path / "logs"
        assert (tmp_path / "run").is_dir()
        assert (tmp_path / "logs").is_dir()

    def test_backups_dir_defaults_next_to_the_db(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"

        assert _Paths.backups_dir(db_path) == tmp_path / "db" / "backups"
        assert (tmp_path / "db" / "backups").is_dir()

    def test_backups_dir_is_not_created_on_request(self, tmp_path):
        db_path = tmp_path / "db" / "vethuq.db"

        _Paths.backups_dir(db_path, create=False)

        assert not (tmp_path / "db" / "backups").exists()

    def test_app_name_comes_from_the_brand(self):
        assert _Paths.APP_NAME == vethuq.APP_NAME

    def test_config_file_is_named_db_json(self):
        assert _Paths.location_file().name == "db.json"
        assert _Paths.LOCATION_FILENAME == "db.json"


class TestLocation:
    def test_precedence_env_then_file_then_default(self, tmp_path, monkeypatch):
        default = _Paths.platform_data_root()
        assert _Paths.resolve_data_root() == default
        _Paths.save_location(tmp_path / "saved")
        assert _Paths.resolve_data_root() == tmp_path / "saved"
        monkeypatch.setenv(_Paths.ENV_VAR, str(tmp_path / "env"))
        assert _Paths.resolve_data_root() == tmp_path / "env"

    def test_pointer_file_stores_only_the_location(self, tmp_path):
        _Paths.save_location(tmp_path / "saved")

        assert list(json.loads(_Paths.location_file().read_text())) == [_Paths.LOCATION_KEY]

    def test_clear_location_removes_the_file_when_nothing_is_left(self, tmp_path):
        _Paths.save_location(tmp_path / "saved")

        _Paths.clear_location()

        assert not _Paths.location_file().exists()
        assert _Paths.configured_location() is None

    def test_backups_location_round_trips_alongside_the_location(self, tmp_path):
        _Paths.save_location(tmp_path / "saved")
        _Paths.save_backups_location(tmp_path / "bk")

        assert _Paths.configured_location() == tmp_path / "saved"
        assert _Paths.configured_backups_location() == tmp_path / "bk"
        _Paths.clear_backups_location()
        assert _Paths.configured_backups_location() is None
        assert _Paths.configured_location() == tmp_path / "saved"

    def test_unreadable_file_is_ignored(self):
        file = _Paths.location_file()
        file.parent.mkdir(parents=True)
        file.write_text("{not json", encoding="utf-8")

        assert _Paths.configured_location() is None

    def test_move_data_moves_folders_and_repoints(self, tmp_path):
        src, dst = tmp_path / "default", tmp_path / "new"
        for name in ("db", "run", "logs"):
            (src / name).mkdir(parents=True)
            (src / name / "f.txt").write_text(name)

        _Paths.move_data(src, dst)

        assert (dst / "db" / "f.txt").read_text() == "db"
        assert not (src / "db").exists()
        assert _Paths.resolve_data_root() == dst

    def test_plan_move_refuses_nested_and_populated_targets(self, tmp_path):
        src = tmp_path / "default"
        (src / "db").mkdir(parents=True)
        with pytest.raises(ValueError):
            _Paths.plan_move(src, src / "inner")
        (tmp_path / "new" / "db").mkdir(parents=True)
        (tmp_path / "new" / "db" / "x").write_text("x")
        with pytest.raises(ValueError):
            _Paths.plan_move(src, tmp_path / "new")

    def test_plan_move_refuses_the_same_place(self, tmp_path):
        with pytest.raises(ValueError):
            _Paths.plan_move(tmp_path, tmp_path)


class TestPublicPaths:
    def test_module_is_reachable_from_the_package(self):
        assert vethuq.paths is paths

    def test_constants(self):
        assert paths.Paths.DB_NAME == "vethuq.db"
        assert paths.Paths.CONFIG_FILENAME == "db.json"
        assert paths.Paths.ENV_VAR == "VETHUQ_HOME"

    def test_paths_are_consistent_with_each_other(self):
        root = paths.Paths.data_root()

        assert paths.Paths.db_dir() == root / "db"
        assert paths.Paths.db_path() == root / "db" / "vethuq.db"
        assert paths.Paths.backups_dir() == root / "db" / "backups"
        assert paths.Paths.run_dir() == root / "run"
        assert paths.Paths.logs_dir() == root / "logs"
        assert paths.Paths.config_file().name == "db.json"

    def test_data_root_honours_the_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv(paths.Paths.ENV_VAR, str(tmp_path / "env"))

        assert paths.Paths.data_root() == tmp_path / "env"
        assert paths.Paths.db_path() == tmp_path / "env" / "db" / "vethuq.db"

    def test_data_root_honours_the_saved_location(self, tmp_path):
        _Paths.save_location(tmp_path / "saved")

        assert paths.Paths.data_root() == tmp_path / "saved"

    def test_backups_dir_honours_the_saved_backups_location(self, tmp_path):
        _Paths.save_backups_location(tmp_path / "bk")

        assert paths.Paths.backups_dir() == tmp_path / "bk"

    def test_reading_paths_creates_nothing_on_disk(self, tmp_path, monkeypatch):
        monkeypatch.setenv(paths.Paths.ENV_VAR, str(tmp_path / "env"))

        for name in ("data_root", "db_dir", "db_path", "backups_dir", "run_dir", "logs_dir"):
            getattr(paths.Paths, name)()

        assert not (tmp_path / "env").exists()

    def test_public_module_exports_only_paths(self):
        namespace: dict[str, object] = {}
        exec("from vethuq.paths import *", namespace)  # noqa: S102

        assert paths.__all__ == ["Paths"]
        assert [n for n in namespace if not n.startswith("__")] == ["Paths"]
