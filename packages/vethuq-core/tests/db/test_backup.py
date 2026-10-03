import gzip
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from vethuq_core.db import Db
from vethuq_core.db.backup import Backup, BackupError
from vethuq_core.settings import DbSettings, InvalidSettingValueError, Settings
from vethuq_core.storage import open_storage


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "db" / "vethuq.db"
    path.parent.mkdir()
    Db.connect(path).close()
    for info in Backup.entries(path):
        info.path.unlink()
    return path


def _age(info, days: int) -> None:
    stamp = (datetime.now(UTC) - timedelta(days=days)).timestamp()
    os.utime(info.path, (stamp, stamp))


class TestCreate:
    def test_creates_compressed_backup_that_is_a_valid_database(self, db_path, tmp_path):
        info = Backup.create(db_path, "before-upgrade")

        assert info.name == "before-upgrade"
        assert info.kind == "manual"
        restored = tmp_path / "check.db"
        restored.write_bytes(gzip.decompress(info.path.read_bytes()))
        assert Backup._integrity_messages(restored) == ["ok"]

    def test_generates_a_name_when_none_given(self, db_path):
        assert Backup.create(db_path).name

    @pytest.mark.parametrize("name", ["bad name", "../escape", "auto-1", "safety-1", ""])
    def test_rejects_invalid_or_reserved_names(self, db_path, name):
        with pytest.raises(BackupError):
            Backup.create(db_path, name)

    def test_rejects_duplicate_name(self, db_path):
        Backup.create(db_path, "one")
        with pytest.raises(BackupError, match="already exists"):
            Backup.create(db_path, "one")

    def test_refuses_to_back_up_a_database_that_fails_its_check(self, db_path, monkeypatch):
        monkeypatch.setattr(Backup, "_integrity_messages", staticmethod(lambda p: ["bad page"]))
        with pytest.raises(BackupError, match="integrity"):
            Backup.create(db_path, "x")
        assert Backup.entries(db_path) == []

    def test_fails_without_a_database(self, tmp_path):
        with pytest.raises(BackupError, match="no database"):
            Backup.create(tmp_path / "missing.db")


class TestListDeletePrune:
    def test_entries_newest_first_and_delete(self, db_path):
        first = Backup.create(db_path, "first")
        _age(first, 2)
        Backup.create(db_path, "second")

        assert [b.name for b in Backup.entries(db_path)][:2] == ["second", "first"]
        Backup.delete(db_path, "first")
        assert "first" not in [b.name for b in Backup.entries(db_path)]

    def test_delete_unknown_raises(self, db_path):
        with pytest.raises(BackupError):
            Backup.delete(db_path, "nope")

    def test_prune_removes_old_auto_but_keeps_newest_and_manual(self, db_path):
        autos = [Backup.create(db_path, prefix=Backup.AUTO_PREFIX) for _ in range(5)]
        for index, info in enumerate(autos):
            _age(info, 30 + index)
        manual = Backup.create(db_path, "mine")
        _age(manual, 100)

        removed = Backup.prune(db_path, retention_days=7)

        names = {b.name for b in Backup.entries(db_path)}
        assert removed == 2
        assert "mine" in names
        assert len([n for n in names if n.startswith(Backup.AUTO_PREFIX)]) == Backup.MIN_KEPT


class TestAutoBackup:
    def test_first_connect_takes_one_backup_then_waits_for_the_interval(self, tmp_path):
        path = tmp_path / "db" / "vethuq.db"
        path.parent.mkdir()
        Db.connect(path).close()
        Db.connect(path).close()

        autos = [b for b in Backup.entries(path) if b.kind == "auto"]
        assert len(autos) == 1

    def test_disabled_takes_no_backup(self, db_path):
        for info in Backup.entries(db_path):
            info.path.unlink()
        storage = open_storage(db_path)
        try:
            DbSettings.set_backup(storage, "disable")
            Settings.set(storage, Backup.LAST_RUN_AT_KEY, "2000-01-01T00:00:00+00:00")

            assert Backup.maybe_run_auto(storage, db_path) is None
        finally:
            storage.close()
        assert Backup.entries(db_path) == []

    def test_failure_never_blocks_opening(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            Backup, "create", staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
        )
        path = tmp_path / "db" / "vethuq.db"
        path.parent.mkdir()

        Db.connect(path).close()


class TestRestore:
    def test_restores_a_backup_and_keeps_a_safety_copy(self, db_path):
        storage = open_storage(db_path)
        DbSettings.set_backup_retention_days(storage, 3)
        storage.commit()
        storage.close()
        Backup.create(db_path, "good")
        storage = open_storage(db_path)
        DbSettings.set_backup_retention_days(storage, 9)
        storage.commit()
        storage.close()

        safety = Backup.restore(db_path, "good")

        assert safety is not None and safety.kind == "safety"
        storage = open_storage(db_path)
        try:
            assert DbSettings.get_backup_retention_days(storage) == 3
        finally:
            storage.close()

    def test_rejects_a_damaged_backup_and_leaves_the_database_alone(self, db_path, tmp_path):
        bad = tmp_path / "bad.db.gz"
        bad.write_bytes(gzip.compress(b"this is not a database"))
        before = db_path.read_bytes()

        with pytest.raises(BackupError, match="damaged"):
            Backup.restore(db_path, str(bad))

        assert db_path.read_bytes() == before

    def test_rejects_a_backup_from_a_newer_schema(self, db_path, tmp_path, monkeypatch):
        Backup.create(db_path, "x")
        monkeypatch.setattr(
            Backup, "_schema_version", staticmethod(lambda p: Db.SCHEMA_VERSION + 1)
        )
        with pytest.raises(BackupError, match="newer"):
            Backup.restore(db_path, "x")

    def test_unknown_backup(self, db_path):
        with pytest.raises(BackupError, match="No backup"):
            Backup.restore(db_path, "nope")


class TestReset:
    def test_clears_the_database_after_a_safety_backup(self, db_path):
        safety = Backup.reset(db_path)

        assert safety is not None
        assert not db_path.exists()
        Db.connect(db_path).close()  # a fresh database is created on next use


class TestRepair:
    def test_reindex_on_a_healthy_database_passes(self, db_path):
        result, safety = Backup.repair(db_path)

        assert result.ok
        assert safety is not None

    def test_returns_a_result_for_a_damaged_database(self, db_path):
        data = bytearray(db_path.read_bytes())
        data[4096 * 2 : 4096 * 2 + 200] = b"\xff" * 200
        db_path.write_bytes(bytes(data))
        for suffix in ("-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)

        result, _ = Backup.repair(db_path)

        assert isinstance(result.ok, bool)

    def test_requires_a_database(self, tmp_path):
        with pytest.raises(BackupError):
            Backup.repair(tmp_path / "none.db")


class TestSettings:
    def test_defaults(self, db_path):
        storage = open_storage(db_path)
        try:
            assert DbSettings.get_backup(storage) == "enable"
            assert DbSettings.get_backup_interval_minutes(storage) == 1440
            assert DbSettings.get_backup_retention_days(storage) == 7
        finally:
            storage.close()

    def test_validation(self, db_path):
        storage = open_storage(db_path)
        try:
            with pytest.raises(InvalidSettingValueError):
                DbSettings.set_backup(storage, "auto")
            with pytest.raises(InvalidSettingValueError):
                DbSettings.set_backup_interval_minutes(storage, 0)
            with pytest.raises(InvalidSettingValueError):
                DbSettings.set_backup_retention_days(storage, 0)
        finally:
            storage.close()
