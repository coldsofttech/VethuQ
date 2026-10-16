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

    def test_licence_tokens_are_each_addons_licence_setting(self, db_path):
        _Host("a", db_path, lambda: None).set_setting("licence", "token-a")
        _Host("b", db_path, lambda: None).set_setting("licence", "token-b")
        _Host("c", db_path, lambda: None).set_setting("licence", "")
        _Host("d", db_path, lambda: None).set_setting("other", "x")
        assert _Host("a", db_path, lambda: None).licence_tokens() == {
            "a": "token-a",
            "b": "token-b",
        }

    def test_licence_tokens_without_a_database_are_empty(self, tmp_path):
        assert _Host("a", tmp_path / "none.db", lambda: None).licence_tokens() == {}
        assert not (tmp_path / "none.db").exists()

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

    def test_revoked_signing_key_ids_are_in_the_same_list_licences_are_checked_against(
        self, db_path
    ):
        from vethuq._paths import _Paths  # noqa: PLC0415
        from vethuq._policy import _PolicyState, _PolicyStore  # noqa: PLC0415

        store = _PolicyStore(_Paths.policy_dir(db_path))
        store.write_state(_PolicyState().with_revoked(["lic-0123456789abcdef"]))

        host = _Host("backup", db_path, lambda: None)

        assert host.revoked_licence_ids() == frozenset({"lic-0123456789abcdef"})

    def test_without_a_cached_policy_nothing_is_revoked_and_it_is_enabled(self, db_path):
        host = _Host("backup", db_path, lambda: None)
        assert host.revoked_licence_ids() == frozenset()
        assert host.addon_policy_enabled() is True

    def test_log_goes_to_the_database_log(self, db_path, caplog):
        with caplog.at_level(logging.INFO, logger="vethuq.database"):
            _Host("backup", db_path, lambda: None).log(logging.INFO, "hello")
        assert "addon backup: hello" in caplog.text


class TestTrustedNow:
    """`Host.trusted_now`: the policy-corrected clock, so setting the clock back changes nothing."""

    def test_it_is_the_policy_clock(self, db_path, monkeypatch):
        from datetime import UTC, datetime

        from vethuq._policy import _PolicyClient

        later = datetime(2030, 1, 1, tzinfo=UTC)
        monkeypatch.setattr(_PolicyClient, "now", lambda self: later)
        assert _Host("a", db_path, lambda: None).trusted_now() == later

    def test_without_a_policy_it_is_the_local_clock(self, db_path):
        from datetime import UTC, datetime, timedelta

        moment = _Host("a", db_path, lambda: None).trusted_now()
        assert moment.tzinfo is not None
        assert abs(moment - datetime.now(UTC)) < timedelta(seconds=30)

    def test_a_clock_problem_never_raises(self, db_path, monkeypatch):
        from datetime import UTC, datetime, timedelta

        from vethuq._policy import _PolicyClient

        def broken(self):
            raise OSError("no clock")

        monkeypatch.setattr(_PolicyClient, "now", broken)
        assert abs(_Host("a", db_path, lambda: None).trusted_now() - datetime.now(UTC)) < timedelta(
            seconds=30
        )

    def test_an_injected_policy_source_uses_the_local_clock(self, db_path):
        from datetime import UTC, datetime, timedelta

        host = _Host("a", db_path, lambda: None, policy=lambda: None)
        assert abs(host.trusted_now() - datetime.now(UTC)) < timedelta(seconds=30)


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
        always = {
            "case",
            "csv",
            "english",
            "exact",
            "full-text",
            "fuzzy",
            "leetspeak",
            "lexical",
            "like",
            "markdown",
            "noise-fuzzy",
            "ocr-quick",
            "paddle",
            "pdf",
            "proximity",
            "txt",
            "unicode",
        }  # installed with VethuQ
        before = set(manager.loaded())
        assert always <= before and before - always <= {
            "semantic",
            "png",
            "jpg",
            "tiff",
            "tsv",
        }  # extras
        folder = tmp_path / "site"
        folder.mkdir()
        try:
            AddonFactory.install(folder)
            assert set(manager.loaded()) == before
            manager.reload()
            assert set(manager.loaded()) == before | {"dummy"}
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


class TestLanguageSpecs:
    @pytest.fixture
    def folder(self, tmp_path, monkeypatch):
        path = tmp_path / "langs"
        path.mkdir()
        monkeypatch.setattr(sys, "path", [str(path), *sys.path])
        return path

    def specs(self, db_path):
        return _AddonManager(db_path, lambda: None).language_specs()

    def test_english_comes_from_its_addon(self, db_path):
        (english,) = self.specs(db_path)
        assert (english.id, english.default) == ("en", True)

    def test_other_languages_follow_the_default_by_id(self, folder, db_path):
        from tests.language_addons import TELUGU, LanguageAddonFactory

        module = LanguageAddonFactory.install(folder, "telugu", [TELUGU])
        try:
            assert [s.id for s in self.specs(db_path)] == ["en", "te"]
        finally:
            LanguageAddonFactory.forget(module)

    def test_the_first_addon_to_offer_a_language_wins(self, folder, db_path):
        from tests.language_addons import LanguageAddonFactory

        other = {"id": "en", "label": "Another English"}
        module = LanguageAddonFactory.install(folder, "zzz", [other])
        try:
            (english,) = self.specs(db_path)
            assert english.label == "English"  # "english" sorts before "zzz"
        finally:
            LanguageAddonFactory.forget(module)

    def test_an_addon_that_fails_is_skipped(self, folder, db_path):
        from tests.language_addons import LanguageAddonFactory

        module = LanguageAddonFactory.install(folder, "broken", [{"bogus_field": 1}])
        try:
            assert [s.id for s in self.specs(db_path)] == ["en"]
        finally:
            LanguageAddonFactory.forget(module)

    def test_an_incompatible_addon_provides_nothing(self, folder, db_path):
        AddonFactory.install(folder, "dummy", api=', api_min="9.0.0", api_max="9.9.0"')
        try:
            assert [s.id for s in self.specs(db_path)] == ["en"]
        finally:
            AddonFactory.forget("vethuq_addon_dummy")
