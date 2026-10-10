import pytest
from policy_factory import PolicySigner
from vethuq_core.policy import Policy, PolicyResult, PolicyService, PolicySource, PolicyStatus
from vethuq_core.policy.baseline import Baseline
from vethuq_core.settings import UpdateSettings
from vethuq_core.storage import Storage
from vethuq_core.updates import UpdateChecker, UpdateStatus

NOW = 1_000_000.0
DAY = 24 * 60 * 60


def policy_result(latest="1.2.0", minimum="1.0.0", dist="pip", notes=None, **fields):
    entry = {"latest": latest, "minimum_supported": minimum}
    if notes:
        entry["release_notes_url"] = notes
    payload = PolicySigner("k").payload(
        1, kid="k", versions={"desktop": dict(entry), "pip": dict(entry)}
    )
    return PolicyResult(
        Policy.from_payload(payload), PolicySource.CACHE, PolicyStatus.CURRENT, **fields
    )


def evaluate(storage: Storage, result, current="1.0.0", mode="on", dist="pip"):
    return UpdateChecker.evaluate(storage, result, mode, current, dist, now=NOW)


class TestEvaluate:
    def test_up_to_date(self, storage: Storage):
        r = evaluate(storage, policy_result(), current="1.2.0")
        assert r.status is UpdateStatus.UP_TO_DATE and not r.notify and r.message == ""

    def test_newer_than_latest_is_up_to_date(self, storage: Storage):
        assert evaluate(storage, policy_result(), current="1.3.0").status is UpdateStatus.UP_TO_DATE

    def test_update_available(self, storage: Storage):
        r = evaluate(storage, policy_result(notes="https://example.com/n"), current="1.1.0")
        assert r.status is UpdateStatus.AVAILABLE
        assert (r.latest, r.minimum_supported) == ("1.2.0", "1.0.0")
        assert r.release_notes_url == "https://example.com/n"
        assert r.notify and r.offer_install
        assert "1.2.0" in r.message and "1.1.0" in r.message

    def test_notify_only_never_offers_the_install(self, storage: Storage):
        r = evaluate(storage, policy_result(), current="1.1.0", mode="notify-only")
        assert r.notify is True and r.offer_install is False

    def test_below_minimum(self, storage: Storage):
        r = evaluate(storage, policy_result(minimum="1.1.0"), current="1.0.0")
        assert r.status is UpdateStatus.BELOW_MINIMUM and r.notify
        assert "local features keep working" in r.message.lower()

    def test_distribution_picks_its_own_entry(self, storage: Storage):
        payload = PolicySigner("k").payload(
            1,
            kid="k",
            versions={
                "desktop": {"latest": "2.0.0", "minimum_supported": "1.0.0"},
                "pip": {"latest": "1.0.0", "minimum_supported": "1.0.0"},
            },
        )
        result = PolicyResult(
            Policy.from_payload(payload), PolicySource.CACHE, PolicyStatus.CURRENT
        )
        assert evaluate(storage, result, "1.0.0", dist="pip").status is UpdateStatus.UP_TO_DATE
        assert evaluate(storage, result, "1.0.0", dist="desktop").status is UpdateStatus.AVAILABLE

    def test_prerelease_is_older_than_its_release(self, storage: Storage):
        r = evaluate(storage, policy_result(latest="1.2.0"), current="1.2.0rc1")
        assert r.status is UpdateStatus.AVAILABLE

    def test_baseline_policy_says_nothing(self, storage: Storage):
        result = PolicyResult(Baseline.policy(), PolicySource.BASELINE, PolicyStatus.CURRENT)
        r = evaluate(storage, result, current="0.1.0")
        assert r.status is UpdateStatus.UNKNOWN and not r.notify

    def test_unknown_distribution_or_version(self, storage: Storage):
        assert evaluate(storage, policy_result(), "unknown").status is UpdateStatus.UNKNOWN
        assert (
            evaluate(storage, policy_result(), "1.0.0", dist="other").status is UpdateStatus.UNKNOWN
        )

    def test_policy_needing_a_newer_client_is_reported(self, storage: Storage):
        r = evaluate(storage, policy_result(update_required=True), current="1.2.0")
        assert r.status is UpdateStatus.UP_TO_DATE and r.notify
        assert r.message == "Update VethuQ to receive new policy."


class TestSnoozeAndSkip:
    def test_snooze_hides_an_available_update_until_it_ends(self, storage: Storage):
        UpdateSettings.snooze(storage, 1, now=NOW)
        hidden = UpdateChecker.evaluate(
            storage, policy_result(), "on", "1.1.0", "pip", now=NOW + DAY - 1
        )
        assert hidden.status is UpdateStatus.AVAILABLE and hidden.snoozed and not hidden.notify
        shown = UpdateChecker.evaluate(
            storage, policy_result(), "on", "1.1.0", "pip", now=NOW + DAY + 1
        )
        assert shown.notify

    def test_skip_hides_that_version_only(self, storage: Storage):
        UpdateSettings.skip_version(storage, "1.2.0")
        r = evaluate(storage, policy_result(latest="1.2.0"), current="1.1.0")
        assert r.skipped and not r.notify
        newer = evaluate(storage, policy_result(latest="1.3.0"), current="1.1.0")
        assert not newer.skipped and newer.notify

    def test_below_minimum_ignores_snooze_and_skip(self, storage: Storage):
        UpdateSettings.snooze(storage, 7, now=NOW)
        UpdateSettings.skip_version(storage, "1.2.0")
        r = evaluate(storage, policy_result(minimum="1.1.0"), current="1.0.0")
        assert r.status is UpdateStatus.BELOW_MINIMUM and r.notify


class TestStatusAndCheck:
    @pytest.fixture(autouse=True)
    def _clean_environment(self, monkeypatch):
        monkeypatch.delenv(UpdateSettings.ENV_VAR, raising=False)
        monkeypatch.setattr("vethuq_core.updates.versions.Versions.installed", lambda: "1.0.0")

    def test_off_setting_disables_without_reading_the_policy(self, storage: Storage, monkeypatch):
        UpdateSettings.set_check(storage, "off")
        monkeypatch.setattr(PolicyService, "current", lambda *a, **k: pytest.fail("read policy"))
        r = UpdateChecker.status(storage)
        assert r.status is UpdateStatus.DISABLED and not r.notify
        assert r.disabled_by_environment is False

    def test_environment_variable_disables(self, storage: Storage, monkeypatch):
        monkeypatch.setenv(UpdateSettings.ENV_VAR, "off")
        r = UpdateChecker.status(storage)
        assert r.status is UpdateStatus.DISABLED and r.disabled_by_environment is True

    def test_status_uses_the_saved_policy(self, storage: Storage, monkeypatch):
        monkeypatch.setattr(PolicyService, "current", lambda *a, **k: policy_result())
        monkeypatch.setattr("vethuq_core.updates.distribution.Distribution.current", lambda: "pip")
        assert UpdateChecker.status(storage).status is UpdateStatus.AVAILABLE

    def test_status_never_raises(self, storage: Storage, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("broken")

        monkeypatch.setattr(PolicyService, "current", boom)
        assert UpdateChecker.status(storage).status is UpdateStatus.UNKNOWN

    def test_check_refreshes_the_policy(self, storage: Storage, monkeypatch):
        calls = []

        class FakeClient:
            def refresh(self, force=False):
                calls.append(force)
                return policy_result()

        monkeypatch.setattr(PolicyService, "client", lambda *a, **k: FakeClient())
        monkeypatch.setattr("vethuq_core.updates.distribution.Distribution.current", lambda: "pip")
        r = UpdateChecker.check(storage, force=True)
        assert calls == [True] and r.status is UpdateStatus.AVAILABLE

    def test_check_makes_no_request_when_off(self, storage: Storage, monkeypatch):
        UpdateSettings.set_check(storage, "off")
        monkeypatch.setattr(PolicyService, "client", lambda *a, **k: pytest.fail("fetched"))
        assert UpdateChecker.check(storage).status is UpdateStatus.DISABLED

    def test_check_survives_a_failing_refresh(self, storage: Storage, monkeypatch):
        class Broken:
            def refresh(self, force=False):
                raise RuntimeError("offline")

        monkeypatch.setattr(PolicyService, "client", lambda *a, **k: Broken())
        monkeypatch.setattr(PolicyService, "current", lambda *a, **k: policy_result())
        monkeypatch.setattr("vethuq_core.updates.distribution.Distribution.current", lambda: "pip")
        assert UpdateChecker.check(storage).status is UpdateStatus.AVAILABLE
