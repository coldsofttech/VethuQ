from __future__ import annotations

import logging
import sqlite3
import sys

import pytest

import vethuq
from tests.addons_factory import AddonFactory
from tests.policy_factory import PolicySigner
from vethuq._addons import _AddonFinder, _AddonManager, _Host
from vethuq._db import _Schema
from vethuq._policy import Policy
from vethuq_addon_api import API_VERSION, Host


def _policy(**over) -> Policy:
    return Policy.from_payload(PolicySigner().payload(**over))


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "vethuq.db"
    with vethuq.VethuQ(path) as client:
        client.sources.list()
    return path


class TestHost:
    def test_it_satisfies_the_host_protocol(self, db_path):
        assert isinstance(_Host("backup", db_path, lambda: None), Host)

    def test_basic_facts(self, db_path):
        host = _Host("backup", db_path, lambda: None)
        assert host.api_version == API_VERSION
        assert host.db_path == db_path
        assert host.schema_version == _Schema.VERSION
        assert host.app_version

    def test_settings_are_namespaced_per_addon(self, db_path):
        first, second = _Host("a", db_path, lambda: None), _Host("b", db_path, lambda: None)
        first.set_setting("mode", "x")
        assert first.get_setting("mode") == "x"
        assert second.get_setting("mode", "none") == "none"
        first.reset_setting("mode")
        assert first.get_setting("mode") is None

    def test_a_missing_database_gives_the_default(self, tmp_path):
        host = _Host("a", tmp_path / "none.db", lambda: None)
        assert host.get_setting("mode", "d") == "d"

    def test_release_database_calls_back(self, db_path):
        calls = []
        _Host("a", db_path, lambda: calls.append(1)).release_database()
        assert calls == [1]

    def test_revoked_ids_and_kill_switch_come_from_the_policy(self, db_path):
        policy = _policy(revoked_licence_ids=["lic-1"], addons={"backup": {"enabled": False}})
        host = _Host("backup", db_path, lambda: None, policy=lambda: policy)
        assert host.revoked_licence_ids() == frozenset({"lic-1"})
        assert host.addon_policy_enabled() is False
        assert _Host("other", db_path, lambda: None, policy=lambda: policy).addon_policy_enabled()

    def test_without_a_cached_policy_nothing_is_revoked_and_it_is_enabled(self, db_path):
        host = _Host("backup", db_path, lambda: None)
        assert host.revoked_licence_ids() == frozenset()
        assert host.addon_policy_enabled() is True

    def test_log_goes_to_the_database_log(self, db_path, caplog):
        with caplog.at_level(logging.INFO, logger="vethuq.database"):
            _Host("backup", db_path, lambda: None).log(logging.INFO, "hello")
        assert "addon backup: hello" in caplog.text


class TestPolicyModel:
    def test_addons_and_revoked_licences_are_parsed(self):
        policy = _policy(
            addons={"backup": {"enabled": False, "latest": "1.0.0", "message": "off"}, "x": 3},
            revoked_licence_ids=["a", "a", 5, "b"],
        )
        assert policy.addons["backup"].enabled is False
        assert policy.addons["backup"].latest == "1.0.0"
        assert "x" not in policy.addons
        assert policy.revoked_licence_ids == ("a", "b")

    def test_defaults(self):
        policy = _policy()
        assert policy.addons == {}
        assert policy.revoked_licence_ids == ()


class TestFinder:
    @pytest.mark.parametrize(
        ("name", "real"),
        [
            ("vethuq.addons.backup", "vethuq_addon_backup"),
            ("vethuq.addons.backup.sub", "vethuq_addon_backup.sub"),
            ("vethuq.addons.my-addon", "vethuq_addon_my_addon"),
            ("vethuq.sources", None),
            ("vethuq.addons", None),
            ("vethuq.addons.bad/name", None),
        ],
    )
    def test_real_name(self, name, real):
        assert _AddonFinder.real_name(name) == real

    def test_install_is_idempotent(self):
        _AddonFinder.install()
        _AddonFinder.install()
        assert sum(isinstance(f, _AddonFinder) for f in sys.meta_path) == 1

    def test_a_broken_addon_import_error_is_not_hidden(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
        (tmp_path / "vethuq_addon_broken.py").write_text("import not_a_real_dependency_xyz\n")
        with pytest.raises(ModuleNotFoundError, match="not_a_real_dependency_xyz"):
            import vethuq.addons.broken  # noqa: F401


class TestManager:
    def test_reload_looks_again(self, tmp_path, monkeypatch, db_path):
        monkeypatch.setattr(sys, "path", list(sys.path))
        manager = _AddonManager(db_path, lambda: None)
        assert manager.loaded() == {}
        folder = tmp_path / "site"
        folder.mkdir()
        try:
            AddonFactory.install(folder)
            assert manager.loaded() == {}
            manager.reload()
            assert "dummy" in manager.loaded()
        finally:
            AddonFactory.forget("vethuq_addon_dummy")

    def test_hooks_survive_a_failing_addon(self, tmp_path, monkeypatch, db_path):
        monkeypatch.setattr(sys, "path", list(sys.path))
        folder = tmp_path / "site"
        folder.mkdir()
        try:
            AddonFactory.install(folder, open_extra="raise RuntimeError('boom')")
            manager = _AddonManager(db_path, lambda: None)
            manager.on_open()
            manager.before_migration(1, 2)
        finally:
            AddonFactory.forget("vethuq_addon_dummy")

    def test_settings_survive_on_a_database_that_is_not_a_database(self, tmp_path):
        bad = tmp_path / "bad.db"
        bad.write_bytes(b"not a database" * 100)
        host = _Host("a", bad, lambda: None)
        assert host.get_setting("k", "d") == "d"
        with pytest.raises(sqlite3.DatabaseError):
            host.set_setting("k", "v")
