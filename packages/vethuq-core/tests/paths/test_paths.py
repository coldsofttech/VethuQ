from pathlib import Path

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
