"""The device folder: licences and the credit ledger are shared by every account on the computer
(and the background service), and stay when a database is restored or reset."""

from __future__ import annotations

import os
import sqlite3
import threading
import time

import pytest

import vethuq
from vethuq._paths import _Paths
from vethuq._paths.device import _DeviceFolder, _DeviceLicences
from vethuq.paths import Paths

REAL_PLATFORM_DEVICE_ROOT = _Paths.platform_device_root  # before the fixtures replace it


def account(tmp_path, name: str) -> vethuq.VethuQ:
    """A client for an account whose data folder is `<name>/VethuQ` (a standard one)."""
    return vethuq.VethuQ(db_path=tmp_path / name / "VethuQ" / "db" / "vethuq.db")


@pytest.fixture
def shared(tmp_path):
    return _Paths.platform_device_root()


class TestWhereItLives:
    def test_a_standard_data_folder_uses_the_shared_device_folder(self, tmp_path, shared):
        db = tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db"
        found = _DeviceFolder.resolve(db)
        assert (found.path, found.scope, found.shared) == (shared, "device", True)
        assert found.database == shared / "device.db"

    def test_two_accounts_resolve_to_the_same_folder(self, tmp_path, shared):
        a = _DeviceFolder.resolve(tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db")
        b = _DeviceFolder.resolve(tmp_path / "bob" / "VethuQ" / "db" / "vethuq.db")
        assert a.path == b.path == shared

    def test_the_resolved_data_root_counts_as_standard_whatever_it_is_called(
        self, tmp_path, shared, monkeypatch
    ):
        root = tmp_path / "relocated"
        monkeypatch.setenv(_Paths.ENV_VAR, str(root))
        assert _DeviceFolder.resolve(root / "db" / "vethuq.db").scope == "device"

    def test_a_database_anywhere_else_keeps_its_own_device_folder(self, tmp_path, shared):
        found = _DeviceFolder.resolve(tmp_path / "copy" / "db" / "vethuq.db")
        assert (found.path, found.scope, found.shared) == (
            tmp_path / "copy" / "device",
            "database",
            False,
        )
        assert not shared.exists()

    def test_the_environment_names_the_folder(self, tmp_path, shared, monkeypatch):
        monkeypatch.setenv("VETHUQ_DEVICE_HOME", str(tmp_path / "elsewhere"))
        found = _DeviceFolder.resolve(tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db")
        assert (found.path, found.scope) == (tmp_path / "elsewhere", "custom")
        assert found.shared and (tmp_path / "elsewhere").is_dir()

    def test_an_unusable_environment_folder_is_an_error_not_a_fallback(self, tmp_path, monkeypatch):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        monkeypatch.setenv("VETHUQ_DEVICE_HOME", str(blocker / "inside"))
        from vethuq import errors

        with pytest.raises(errors.DataFolderNotWritableError, match="VETHUQ_DEVICE_HOME"):
            _DeviceFolder.resolve(tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db")

    def test_a_shared_folder_that_cannot_be_used_falls_back_to_the_account(
        self, tmp_path, monkeypatch, caplog
    ):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        monkeypatch.setattr(_Paths, "platform_device_root", staticmethod(lambda: blocker / "x"))
        db = tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db"
        with caplog.at_level("WARNING", logger="vethuq.database"):
            found = _DeviceFolder.resolve(db)
        assert (found.path, found.scope, found.shared) == (
            db.parent.parent / "device",
            "user",
            False,
        )
        assert "keeps its own licences and credits" in caplog.text

    def test_the_public_paths_report_it(self, tmp_path, shared, monkeypatch):
        monkeypatch.setenv(_Paths.ENV_VAR, str(tmp_path / "VethuQ"))
        assert Paths.device_dir() == shared and Paths.device_scope() == "device"
        assert Paths.DEVICE_ENV_VAR == "VETHUQ_DEVICE_HOME"

    def test_the_windows_folder_is_under_programdata(self, monkeypatch):
        from pathlib import PureWindowsPath

        import vethuq._paths.paths as module

        monkeypatch.setattr(module.os, "name", "nt")
        monkeypatch.setattr(module, "Path", PureWindowsPath)
        monkeypatch.setenv("PROGRAMDATA", r"D:\ProgData")
        assert str(REAL_PLATFORM_DEVICE_ROOT()) == "D:\\ProgData\\VethuQ"
        monkeypatch.delenv("PROGRAMDATA")
        assert str(REAL_PLATFORM_DEVICE_ROOT()) == "C:\\ProgramData\\VethuQ"

    def test_the_mac_and_linux_folders(self, monkeypatch):
        import vethuq._paths.paths as module

        monkeypatch.setattr(module.sys, "platform", "darwin")
        assert str(REAL_PLATFORM_DEVICE_ROOT()) == "/Users/Shared/VethuQ"
        monkeypatch.setattr(module.sys, "platform", "linux")
        assert str(REAL_PLATFORM_DEVICE_ROOT()) == "/var/lib/vethuq"


class TestPermissions:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_the_shared_folder_and_file_are_open_to_every_account(self, tmp_path, shared):
        with account(tmp_path, "alice") as client:
            client.licences.show()
            client.credits.balance()  # opens the database, so the ledger file exists
        assert shared.stat().st_mode & 0o7777 == 0o1777
        assert (shared / "device.db").stat().st_mode & 0o666 == 0o666

    def test_an_existing_folder_is_left_as_it_is(self, tmp_path, shared):
        shared.mkdir()
        shared.chmod(0o755)
        _DeviceFolder.resolve(tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db")
        assert shared.stat().st_mode & 0o7777 == 0o755

    def test_on_windows_the_users_group_gets_modify_access(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(_DeviceFolder, "_is_windows", staticmethod(lambda: True))
        monkeypatch.setattr(
            "vethuq._paths.device.subprocess.run", lambda args, **kw: calls.append(args)
        )
        _DeviceFolder.prepare(tmp_path / "ProgramData" / "VethuQ")
        assert calls == [
            [
                "icacls",
                str(tmp_path / "ProgramData" / "VethuQ"),
                "/grant",
                "*S-1-5-32-545:(OI)(CI)M",
            ]
        ]

    def test_a_failing_icacls_is_not_fatal(self, tmp_path, monkeypatch):
        import subprocess

        def broken(*args, **kwargs):
            raise subprocess.TimeoutExpired("icacls", 15)

        monkeypatch.setattr(_DeviceFolder, "_is_windows", staticmethod(lambda: True))
        monkeypatch.setattr("vethuq._paths.device.subprocess.run", broken)
        _DeviceFolder.prepare(tmp_path / "x")  # does not raise
        assert (tmp_path / "x").is_dir()


class TestSharedCredits:
    def test_a_grant_redeemed_in_one_account_is_in_the_other(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice, account(tmp_path, "bob") as bob:
            before = bob.credits.balance().one_off
            alice.credits.redeem([{"id": "LIC-1", "amount": 100}])
            assert bob.credits.balance().one_off == before + 100

    def test_a_grant_is_added_once_for_the_whole_computer(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice, account(tmp_path, "bob") as bob:
            assert alice.credits.redeem([{"id": "LIC-1", "amount": 100}])[0].added is True
            assert bob.credits.redeem([{"id": "LIC-1", "amount": 100}])[0].added is False

    def test_a_second_account_does_not_get_a_second_free_allowance(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice:
            first = alice.credits.balance()
        with account(tmp_path, "bob") as bob:
            second = bob.credits.balance()
        assert second.total == first.total and second.daily == first.daily
        grants = account(tmp_path, "carol")
        with grants:
            assert len([g for g in grants.credits.grants() if g.kind == "daily"]) == 1

    def test_the_ledger_lives_in_the_device_database_not_in_the_users(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice:
            alice.credits.redeem([{"id": "LIC-1", "amount": 100}])
        device = sqlite3.connect(shared / "device.db")
        assert device.execute("SELECT count(*) FROM credit_grants").fetchone()[0] >= 1
        device.close()
        main = sqlite3.connect(tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db")
        tables = {r[0] for r in main.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        main.close()
        assert (
            "credit_grants" not in tables and "credit_ledger" not in tables and "sources" in tables
        )

    def test_a_database_somewhere_else_has_a_ledger_of_its_own(self, tmp_path, shared):
        with vethuq.VethuQ(db_path=tmp_path / "copy" / "db" / "vethuq.db") as copy:
            copy.credits.redeem([{"id": "LIC-1", "amount": 100}])
        with account(tmp_path, "alice") as alice:
            assert alice.credits.redeem([{"id": "LIC-1", "amount": 100}])[0].added is True

    def test_a_reset_database_keeps_the_ledger(self, tmp_path, shared):
        db = tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db"
        with account(tmp_path, "alice") as alice:
            alice.credits.redeem([{"id": "LIC-1", "amount": 100}])
        for leftover in db.parent.glob("vethuq.db*"):
            leftover.unlink()  # what a reset or a restore of an older copy does to the database
        with account(tmp_path, "alice") as fresh:
            assert fresh.credits.balance().one_off >= 100
            assert fresh.credits.redeem([{"id": "LIC-1", "amount": 100}])[0].added is False

    def test_removing_a_source_forgets_what_was_spent_on_it_but_not_the_balance(
        self, tmp_path, shared
    ):
        from sqlalchemy import select

        from vethuq._db import _CreditLedger

        docs = tmp_path / "docs"
        docs.mkdir()
        with account(tmp_path, "alice") as alice:
            source = alice.sources.create(docs)
            with alice._db().session() as session:
                session.add(
                    _CreditLedger(at="2026-10-12T10:00:00+00:00", wallet="local", kind="charge",
                                  amount_milli=-500, source_id=source.id)
                )  # fmt: skip
            alice.sources.remove(source.id)
            alice.sources.purge(source.id)
            with alice._db().session() as session:
                assert session.scalars(select(_CreditLedger)).all() == []
            assert alice.credits.balance().total > 0

    def test_writers_in_both_databases_never_deadlock(self, tmp_path, shared):
        """Several accounts and threads write to their own database and to the shared ledger at
        once: the write locks are taken in one order, so they wait for each other."""
        errors: list[BaseException] = []
        clients = [account(tmp_path, name) for name in ("alice", "bob", "carol")]
        for client in clients:
            client.credits.balance()

        def work(client, tag):
            try:
                for n in range(15):
                    client.credits.redeem([{"id": f"{tag}-{n}", "amount": 1}])
                    folder = tmp_path / f"docs-{tag}-{n}"  # a write to the user's own database
                    folder.mkdir()
                    client.sources.create(folder)
            except BaseException as error:  # noqa: BLE001
                errors.append(error)

        threads = [
            threading.Thread(target=work, args=(client, f"{i}-{t}"))
            for i, client in enumerate(clients)
            for t in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        for client in clients:
            client.close()
        assert errors == []
        with account(tmp_path, "dave") as dave:
            assert dave.credits.grants(limit=500)  # all of it landed in the one ledger


class TestLockOrder:
    """One transaction writes to the user's database and then the ledger, another the other way
    round. Without a fixed order SQLite reports a deadlock at once (`database is locked`)."""

    def run_both(self, client):
        from vethuq._db import _CreditGrant, _Source
        from vethuq.enums import SourceType

        db = client._db()
        db.session().__enter__().close()  # open it (creates the tables)
        failures: list[BaseException] = []

        def source(path):
            return _Source(
                path=path, source_type=SourceType.FOLDER, added_at="2026-10-12T10:00:00+00:00"
            )

        def grant(ref):
            return _CreditGrant(
                wallet="local", kind="one_off", origin="test", ref=ref, amount_milli=1,
                remaining_milli=1, granted_at="2026-10-12T10:00:00+00:00",
            )  # fmt: skip

        def user_first():
            try:
                with db.session() as session:
                    session.add(source("/a"))
                    session.flush()
                    time.sleep(0.3)  # long enough for the other transaction to take its first lock
                    session.add(grant("a"))
                    session.flush()
            except BaseException as error:  # noqa: BLE001
                failures.append(error)

        def ledger_first():
            try:
                with db.session() as session:
                    session.add(grant("b"))
                    session.flush()
                    time.sleep(0.3)  # long enough for the other transaction to take its first lock
                    session.add(source("/b"))
                    session.flush()
            except BaseException as error:  # noqa: BLE001
                failures.append(error)

        threads = [threading.Thread(target=user_first), threading.Thread(target=ledger_first)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        return failures

    def test_the_two_orders_wait_for_each_other_instead_of_failing(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice:
            assert self.run_both(alice) == []


class TestSharedLicences:
    def test_a_licence_installed_by_one_account_is_seen_by_the_other(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice, account(tmp_path, "bob") as bob:
            alice.addons.settings("csv").set("licence", "VQLIC1.abc")
            assert bob.addons.settings("csv").get("licence") == "VQLIC1.abc"

    def test_the_licence_is_in_the_device_folder_not_the_database(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice:
            alice.addons.settings("csv").set("licence", "VQLIC1.abc")
            alice.addons.settings("csv").set("mode", "fast")
        assert _DeviceLicences(tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db").all() == {
            "csv": "VQLIC1.abc"
        }
        main = sqlite3.connect(tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db")
        keys = {r[0] for r in main.execute("SELECT key FROM settings")}
        main.close()
        assert "addon.csv.mode" in keys and "addon.csv.licence" not in keys

    def test_removing_it_removes_it_for_everyone(self, tmp_path, shared):
        with account(tmp_path, "alice") as alice, account(tmp_path, "bob") as bob:
            alice.addons.settings("csv").set("licence", "VQLIC1.abc")
            bob.addons.settings("csv").reset("licence")
            assert alice.addons.settings("csv").get("licence") is None

    def test_the_host_and_the_installer_use_the_same_store(self, tmp_path, shared):
        from vethuq._addons.host import _Host

        db = tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db"
        with account(tmp_path, "alice") as alice:
            alice.addons.settings("csv").set("licence", "VQLIC1.abc")
        host = _Host("csv", db, lambda: None)
        assert host.get_setting("licence") == "VQLIC1.abc"
        assert host.licence_tokens() == {"csv": "VQLIC1.abc"}
        host.reset_setting("licence")
        assert host.licence_tokens() == {}

    def test_a_licence_an_older_version_kept_in_the_database_is_still_read(self, tmp_path, shared):
        db = tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db"
        with account(tmp_path, "alice") as alice:
            alice.addons.settings("csv").set("mode", "x")  # opens the database
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO settings (key, value) VALUES ('addon.csv.licence', 'VQLIC1.old')")
        conn.commit()
        conn.close()
        with account(tmp_path, "alice") as alice:
            assert alice.addons.settings("csv").get("licence") == "VQLIC1.old"
            alice.addons.settings("csv").set("licence", "VQLIC1.new")  # replaces it for good
            assert alice.addons.settings("csv").get("licence") == "VQLIC1.new"
        conn = sqlite3.connect(db)
        assert (
            conn.execute(
                "SELECT count(*) FROM settings WHERE key = 'addon.csv.licence'"
            ).fetchone()[0]
            == 0
        )
        conn.close()

    def test_licences_can_be_read_while_the_database_cannot(self, tmp_path, shared):
        db = tmp_path / "alice" / "VethuQ" / "db" / "vethuq.db"
        with account(tmp_path, "alice") as alice:
            alice.addons.settings("csv").set("licence", "VQLIC1.abc")
        db.write_bytes(b"not a database" * 100)
        from vethuq._addons import _AddonSettingsStore

        assert _AddonSettingsStore.licences(db) == {"csv": "VQLIC1.abc"}

    def test_a_missing_device_database_has_no_licences(self, tmp_path, shared):
        assert _DeviceLicences(tmp_path / "x" / "VethuQ" / "db" / "vethuq.db").all() == {}
        _DeviceLicences(tmp_path / "x" / "VethuQ" / "db" / "vethuq.db").reset("csv")  # no error
