from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

import vethuq
from tests.policy_factory import PolicySigner
from vethuq import errors
from vethuq._policy import _FetchResponse, _PolicyKeys


class _FakeFetcher:
    """Replaces the network: serves one envelope, or fails."""

    envelope: bytes | None = None
    calls = 0

    def __init__(self, urls=()):
        self.urls = urls

    def attempts(self, etag_url=None, etag=None):
        type(self).calls += 1
        if type(self).envelope is not None:
            yield _FetchResponse("https://h/p", type(self).envelope, None)


@pytest.fixture
def signer():
    return PolicySigner()


@pytest.fixture
def published(monkeypatch, signer):
    """A VethuQ that trusts `signer` and can fetch whatever `published.set(...)` publishes."""
    monkeypatch.setattr(_PolicyKeys, "EMBEDDED", (signer.key,))
    monkeypatch.setattr("vethuq._policy.client._PolicyFetcher", _FakeFetcher)
    monkeypatch.setattr(
        "vethuq._updates.versions._Versions.installed", staticmethod(lambda: "1.5.0")
    )
    _FakeFetcher.envelope, _FakeFetcher.calls = None, 0

    class Published:
        @staticmethod
        def set(raw):
            _FakeFetcher.envelope = raw

        calls = staticmethod(lambda: _FakeFetcher.calls)

    return Published


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


@pytest.fixture(autouse=True)
def _no_update_override(monkeypatch):
    monkeypatch.delenv("VETHUQ_UPDATE_CHECK", raising=False)


def _pip(latest: str, minimum: str) -> dict:
    return {"pip": {"latest": latest, "minimum_supported": minimum}}


class TestPolicyAccess:
    def test_is_available_on_the_client_and_as_a_module(self, client):
        assert isinstance(client.policy, vethuq.policy.PolicyClient)
        assert client.policy is client.policy
        assert vethuq.policy.Policy is not None

    def test_the_types_live_in_vethuq_policy(self):
        for name in ("Policy", "PolicyResult", "Notice", "Feature", "DistributionVersions"):
            assert name in vethuq.policy.__all__ and not hasattr(vethuq, name)

    def test_nothing_is_read_or_created_until_it_is_used(self, tmp_path):
        client = vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db")

        client.policy

        assert not (tmp_path / "policy").exists() and not (tmp_path / "logs").exists()

    def test_the_cache_folder_sits_next_to_the_database_folder(self, client, tmp_path):
        assert client.policy.directory == tmp_path / "policy"

    def test_paths_reports_the_policy_folder(self):
        assert vethuq.Paths.policy_dir() == vethuq.Paths.data_root() / "policy"


class TestCurrentAndRefresh:
    def test_before_anything_is_fetched_the_baseline_applies(self, client):
        result = client.policy.current()

        assert result.source is vethuq.policy.PolicySource.BASELINE
        assert result.status is vethuq.policy.PolicyStatus.CURRENT
        assert result.policy.sequence == 0

    def test_without_embedded_keys_refresh_makes_no_request(self, client, monkeypatch):
        monkeypatch.setattr("vethuq._policy.client._PolicyFetcher", _FakeFetcher)
        _FakeFetcher.calls = 0

        result = client.policy.refresh(force=True)

        assert result.status is vethuq.policy.PolicyStatus.SKIPPED
        assert _FakeFetcher.calls == 0

    def test_refresh_accepts_and_caches_a_signed_policy(self, client, published, signer, tmp_path):
        published.set(signer.signed(4))

        result = client.policy.refresh()

        assert result.status is vethuq.policy.PolicyStatus.UPDATED and result.policy.sequence == 4
        assert (tmp_path / "policy" / "policy.json").is_file()
        again = client.policy.current()
        assert again.source is vethuq.policy.PolicySource.CACHE and again.policy.sequence == 4

    def test_a_second_client_sees_the_cached_policy(self, client, published, signer):
        published.set(signer.signed(4))
        client.policy.refresh()

        with vethuq.VethuQ(db_path=client.db_path) as other:
            assert other.policy.current().policy.sequence == 4

    def test_refresh_never_raises_when_the_policy_is_bad(self, client, published, signer):
        published.set(PolicySigner("test-1").signed(1))  # the right key id, the wrong key

        result = client.policy.refresh()

        assert result.status is vethuq.policy.PolicyStatus.REJECTED

    def test_refresh_in_background(self, client, published, signer):
        published.set(signer.signed(2))

        thread = client.policy.refresh_in_background()
        thread.join(timeout=5)

        assert isinstance(thread, threading.Thread) and thread.daemon
        assert client.policy.current().policy.sequence == 2

    def test_notices_are_available_from_the_policy(self, client, published, signer):
        published.set(signer.signed(1, notices=[{"id": "n", "message": "Maintenance soon"}]))
        client.policy.refresh()

        (notice,) = client.policy.current().policy.active_notices()

        assert notice.message == "Maintenance soon"

    def test_the_policy_is_logged_to_the_policy_log(self, client, published, signer):
        published.set(signer.signed(3))
        client.policy.refresh()

        messages = [e.message for e in client.logs.policy.read()]

        assert any(m.startswith("accepted policy sequence 3") for m in messages)
        assert client.logs.policy.file().exists is True

    def test_the_result_has_json(self, client):
        data = json.loads(client.policy.current().to_json())

        assert data["source"] == "baseline" and data["sequence"] == 0


class TestUpdatesCheck:
    def test_no_policy_yet_means_unknown_and_nothing_to_show(self, client, published):
        result = client.updates.status()

        assert result.status is vethuq.updates.UpdateStatus.UNKNOWN
        assert result.notify is False and result.message == ""

    def test_an_available_update(self, client, published, signer):
        published.set(signer.signed(1))

        result = client.updates.check()

        assert result.status is vethuq.updates.UpdateStatus.AVAILABLE
        assert (result.current, result.latest) == ("1.5.0", "2.0.0")
        assert result.notify is True and result.offer_install is True
        assert result.message == "VethuQ 2.0.0 is available (you have 1.5.0)."
        assert result.release_notes_url == "https://example.com/notes"

    def test_up_to_date(self, client, published, signer):
        published.set(signer.signed(1, versions=_pip("1.5.0", "1.0.0")))

        assert client.updates.check().status is vethuq.updates.UpdateStatus.UP_TO_DATE

    def test_below_the_minimum(self, client, published, signer):
        published.set(signer.signed(1, versions=_pip("3.0.0", "2.0.0")))

        result = client.updates.check()

        assert result.status is vethuq.updates.UpdateStatus.BELOW_MINIMUM and result.notify is True

    def test_status_uses_the_saved_policy_and_makes_no_request(self, client, published, signer):
        published.set(signer.signed(1))
        client.updates.check()
        calls = published.calls()

        result = client.updates.status()

        assert result.status is vethuq.updates.UpdateStatus.AVAILABLE
        assert published.calls() == calls

    def test_check_is_limited_to_about_once_a_day_unless_forced(self, client, published, signer):
        published.set(signer.signed(1))
        client.updates.check()
        client.updates.check()
        assert published.calls() == 1

        client.updates.check(force=True)
        assert published.calls() == 2

    def test_the_result_has_json(self, client, published, signer):
        published.set(signer.signed(1))

        data = json.loads(client.updates.check().to_json())

        assert data["status"] == "available" and data["notify"] is True

    def test_a_policy_that_needs_a_newer_vethuq_is_reported(self, client, published, signer):
        published.set(signer.signed(1))
        client.updates.check()
        published.set(signer.signed(2, schema_version=2))

        result = client.updates.check(force=True)

        assert result.policy_update_required is True
        # the last compatible policy still applies
        assert result.status is vethuq.updates.UpdateStatus.AVAILABLE


class TestUpdateSettingsInEffect:
    def test_off_never_checks_and_makes_no_request(self, client, published, signer):
        published.set(signer.signed(1))
        client.settings.updates.set_check("off")

        result = client.updates.check()

        assert result.status is vethuq.updates.UpdateStatus.DISABLED and result.notify is False
        assert published.calls() == 0
        assert client.updates.status().status is vethuq.updates.UpdateStatus.DISABLED

    def test_the_environment_switches_the_check_off_whatever_the_setting(
        self, client, published, signer, monkeypatch
    ):
        published.set(signer.signed(1))
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", "off")

        result = client.updates.check()

        assert result.disabled_by_environment is True and published.calls() == 0
        assert client.settings.updates.disabled_by_environment() is True
        assert client.settings.updates.get_check() is vethuq.updates.UpdateCheckMode.ON

    def test_notify_only_checks_but_does_not_offer_to_install(self, client, published, signer):
        published.set(signer.signed(1))
        client.settings.updates.set_check(vethuq.updates.UpdateCheckMode.NOTIFY_ONLY)

        result = client.updates.check()

        assert result.notify is True and result.offer_install is False
        assert result.mode is vethuq.updates.UpdateCheckMode.NOTIFY_ONLY

    def test_snooze_hides_the_notice(self, client, published, signer):
        published.set(signer.signed(1))
        client.settings.updates.snooze(2)

        result = client.updates.check()

        assert result.status is vethuq.updates.UpdateStatus.AVAILABLE
        assert result.snoozed is True and result.notify is False
        client.settings.updates.clear_snooze()
        assert client.updates.status().notify is True

    def test_skipping_a_version_hides_only_that_version(self, client, published, signer):
        published.set(signer.signed(1))
        client.settings.updates.skip_version("2.0.0")
        assert client.updates.check().notify is False

        published.set(signer.signed(2, versions=_pip("2.1.0", "1.0.0")))
        assert client.updates.check(force=True).notify is True
        client.settings.updates.clear_skip()

    def test_below_the_minimum_ignores_snooze_and_skip(self, client, published, signer):
        published.set(signer.signed(1, versions=_pip("3.0.0", "2.0.0")))
        client.settings.updates.snooze(5)
        client.settings.updates.skip_version("3.0.0")

        assert client.updates.check().notify is True


class TestWhenTheDatabaseIsTooNew:
    def test_the_update_check_still_works(self, tmp_path, published, signer):
        db_path = tmp_path / "vethuq.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
            conn.execute("INSERT INTO schema_version VALUES (99)")
        published.set(signer.signed(1))

        with vethuq.VethuQ(db_path=db_path) as client:
            with pytest.raises(errors.SchemaVersionError):
                client.sources.list()

            result = client.updates.check()

        assert result.status is vethuq.updates.UpdateStatus.AVAILABLE
        assert result.mode is vethuq.updates.UpdateCheckMode.ON

    def test_the_environment_override_still_applies(self, tmp_path, published, monkeypatch):
        db_path = tmp_path / "vethuq.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
            conn.execute("INSERT INTO schema_version VALUES (99)")
        monkeypatch.setenv("VETHUQ_UPDATE_CHECK", "0")

        with vethuq.VethuQ(db_path=db_path) as client:
            assert client.updates.status().status is vethuq.updates.UpdateStatus.DISABLED


class TestFeatures:
    def test_a_feature_the_policy_does_not_cover_keeps_its_default(self, client, published):
        assert client.updates.feature("github_tier", True).allowed is True
        assert client.updates.feature("github_tier", False).allowed is False

    def test_a_kill_switch(self, client, published, signer):
        flag = {"enabled": False, "message": "Paused"}
        published.set(signer.signed(1, features={"github_tier": flag}))
        client.policy.refresh()

        access = client.updates.feature("github_tier", True)

        assert (access.allowed, access.message, access.requires_update) == (False, "Paused", False)

    def test_a_feature_for_newer_versions_needs_an_update(self, client, published, signer):
        published.set(signer.signed(1, features={"new": {"enabled": True, "min_client": "2.0.0"}}))
        client.policy.refresh()

        access = client.updates.feature("new", False)

        assert access.allowed is False and access.requires_update is True

    def test_it_makes_no_request(self, client, published):
        client.updates.feature("x", True)

        assert published.calls() == 0

    def test_it_never_raises(self, client, monkeypatch):
        def boom():
            raise RuntimeError("policy exploded")

        monkeypatch.setattr(client.policy, "current", boom)

        assert client.updates.feature("x", True).allowed is True
        assert client.updates.status().status is vethuq.updates.UpdateStatus.UNKNOWN


class TestUpdateSettingsApi:
    def test_defaults(self, client):
        settings = client.settings.updates

        assert settings.get_check() is vethuq.updates.UpdateCheckMode.ON
        assert settings.get_snoozed_until() is None and settings.get_skipped_version() is None
        assert settings.ENV_VAR == "VETHUQ_UPDATE_CHECK" and settings.DEFAULT_SNOOZE_DAYS == 1

    def test_set_and_reset_the_check(self, client):
        client.settings.updates.set_check("notify-only")
        assert client.settings.updates.get_check() is vethuq.updates.UpdateCheckMode.NOTIFY_ONLY

        client.settings.updates.reset_check()
        assert client.settings.updates.get_check() is vethuq.updates.UpdateCheckMode.ON

    def test_snooze_gives_a_utc_end_time(self, client):
        client.settings.updates.snooze(2)

        until = client.settings.updates.get_snoozed_until()

        assert until.tzinfo is UTC
        remaining = until - datetime.now(UTC)

        assert timedelta(days=1, hours=23) < remaining < timedelta(days=2, minutes=1)

    def test_the_default_snooze_is_a_day(self, client):
        client.settings.updates.snooze()

        until = client.settings.updates.get_snoozed_until()

        assert timedelta(hours=23) < until - datetime.now(UTC) < timedelta(days=1, minutes=1)

    def test_skip_and_clear(self, client):
        client.settings.updates.skip_version("2.0.0")
        assert client.settings.updates.get_skipped_version() == "2.0.0"

        client.settings.updates.clear_skip()
        assert client.settings.updates.get_skipped_version() is None

    @pytest.mark.parametrize(
        ("call", "value"),
        [("set_check", "sometimes"), ("snooze", 0), ("snooze", -1), ("skip_version", "  ")],
    )
    def test_bad_values_are_rejected(self, client, call, value):
        with pytest.raises(errors.InvalidSettingValueError):
            getattr(client.settings.updates, call)(value)

    def test_the_settings_are_kept_in_the_database(self, client):
        client.settings.updates.set_check("off")
        client.settings.updates.skip_version("9.9.9")

        with vethuq.VethuQ(db_path=client.db_path) as other:
            assert other.settings.updates.get_check() is vethuq.updates.UpdateCheckMode.OFF
            assert other.settings.updates.get_skipped_version() == "9.9.9"

    def test_the_settings_object_is_reused(self, client):
        assert client.settings.updates is client.settings.updates
        assert client.updates is client.updates


class TestModuleSurface:
    def test_updates_types_live_in_vethuq_updates(self):
        for name in ("UpdateResult", "UpdateStatus", "UpdateCheckMode", "FeatureAccess", "Updates"):
            assert name in vethuq.updates.__all__ and not hasattr(vethuq, name)

    def test_the_enums_are_the_shared_ones(self):
        assert vethuq.updates.UpdateStatus is vethuq.enums.UpdateStatus
        assert vethuq.policy.PolicyStatus is vethuq.enums.PolicyStatus
