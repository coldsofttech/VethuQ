from __future__ import annotations

import json
import sys

import pytest

from tests.policy_factory import PolicySigner
from vethuq._policy import Policy, PolicyResult, _Baseline
from vethuq._updates import (
    FeatureAccess,
    UpdateResult,
    _Distribution,
    _FeatureGate,
    _UpdateChecker,
    _Versions,
)
from vethuq.enums import PolicySource, PolicyStatus, UpdateCheckMode, UpdateStatus


def _policy_result(
    latest="2.0.0", minimum="1.0.0", source=PolicySource.CACHE, required=False, **extra
):
    versions = {
        "pip": {"latest": latest, "minimum_supported": minimum, "release_notes_url": "https://n"},
        "desktop": {"latest": "9.0.0", "minimum_supported": "9.0.0"},
    }
    policy = Policy.from_payload(PolicySigner().payload(versions=versions, **extra))
    return PolicyResult(policy, source, PolicyStatus.CURRENT, update_required=required)


def _evaluate(current, result=None, mode=UpdateCheckMode.ON, distribution="pip", **kwargs):
    result = result or _policy_result()
    return _UpdateChecker.evaluate(result, mode, current, distribution, **kwargs)


class TestVersions:
    @pytest.mark.parametrize("text", ["1.0.0", "1.2", "2.0.0rc1", " 1.0.0 "])
    def test_parses_pep_440(self, text):
        assert _Versions.parse(text) is not None

    @pytest.mark.parametrize("text", [None, "", "unknown", "one.two", "1.0.0.x.y"])
    def test_anything_else_is_none(self, text):
        assert _Versions.parse(text) is None

    def test_the_policys_prerelease_spelling_reads_as_pep_440(self):
        assert _Versions.parse("1.2.0-rc.1") == _Versions.parse("1.2.0rc1")

    @pytest.mark.parametrize(
        ("have", "wanted", "older"),
        [
            ("1.0.0", "2.0.0", True),
            ("2.0.0", "2.0.0", False),
            ("2.0.1", "2.0.0", False),
            ("2.0.0rc1", "2.0.0", True),
            ("1.9.0", "1.10.0", True),
            ("unknown", "2.0.0", False),
            ("1.0.0", None, False),
            (None, "1.0.0", False),
        ],
    )
    def test_is_older(self, have, wanted, older):
        assert _Versions.is_older(have, wanted) is older

    def test_installed_is_the_vethuq_version(self):
        import vethuq

        assert _Versions.installed() == vethuq.APP_VERSION


class TestDistribution:
    def test_a_normal_install_is_pip(self):
        assert _Distribution.current() == "pip"

    def test_a_frozen_build_is_the_desktop_app(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        assert _Distribution.current() == "desktop"
        assert _Versions.installed() == "unknown"


class TestEvaluate:
    def test_up_to_date(self):
        for current in ("2.0.0", "2.1.0"):
            assert _evaluate(current).status is UpdateStatus.UP_TO_DATE

    def test_an_update_is_available_between_the_minimum_and_the_latest(self):
        result = _evaluate("1.5.0")

        assert result.status is UpdateStatus.AVAILABLE
        assert (result.latest, result.minimum_supported) == ("2.0.0", "1.0.0")
        assert result.release_notes_url == "https://n"
        assert result.notify is True

    def test_below_the_minimum(self):
        assert _evaluate("0.9.0").status is UpdateStatus.BELOW_MINIMUM

    def test_the_minimum_itself_is_supported(self):
        assert _evaluate("1.0.0").status is UpdateStatus.AVAILABLE

    def test_the_baseline_means_unknown(self):
        baseline = PolicyResult(_Baseline.policy(), PolicySource.BASELINE, PolicyStatus.CURRENT)

        result = _evaluate("1.0.0", baseline)

        assert result.status is UpdateStatus.UNKNOWN and result.notify is False

    @pytest.mark.parametrize("current", ["unknown", "", "garbage"])
    def test_a_version_that_cannot_be_compared_means_unknown(self, current):
        assert _evaluate(current).status is UpdateStatus.UNKNOWN

    def test_a_policy_version_that_cannot_be_compared_means_unknown(self):
        assert _evaluate("1.0.0", _policy_result(latest="soon")).status is UpdateStatus.UNKNOWN

    def test_a_distribution_the_policy_lacks_means_unknown(self):
        assert _evaluate("1.0.0", distribution="appliance").status is UpdateStatus.UNKNOWN

    def test_uses_the_entry_for_this_distribution(self):
        assert _evaluate("1.0.0", distribution="desktop").status is UpdateStatus.BELOW_MINIMUM

    def test_the_mode_is_carried_through(self):
        result = _evaluate("1.5.0", mode=UpdateCheckMode.NOTIFY_ONLY)

        assert result.mode is UpdateCheckMode.NOTIFY_ONLY

    def test_a_skipped_version_is_not_announced(self):
        result = _evaluate("1.5.0", skipped_version="2.0.0")

        assert result.skipped is True and result.notify is False

    def test_skipping_one_version_does_not_hide_a_newer_one(self):
        result = _evaluate("1.5.0", _policy_result(latest="2.1.0"), skipped_version="2.0.0")

        assert result.skipped is False and result.notify is True

    def test_a_snoozed_notice_is_hidden(self):
        result = _evaluate("1.5.0", snoozed=True)

        assert result.snoozed is True and result.notify is False

    def test_below_the_minimum_is_never_snoozed_or_skipped(self):
        result = _evaluate("0.5.0", snoozed=True, skipped_version="2.0.0")

        assert result.status is UpdateStatus.BELOW_MINIMUM and result.notify is True

    def test_a_policy_that_needs_a_newer_vethuq_is_reported(self):
        result = _evaluate("2.0.0", _policy_result(required=True))

        assert result.policy_update_required is True and result.notify is True
        assert result.message == UpdateResult.POLICY_MESSAGE

    def test_disabled_result(self):
        result = _UpdateChecker.disabled("1.0.0", "pip", by_environment=True)

        assert result.status is UpdateStatus.DISABLED and result.mode is UpdateCheckMode.OFF
        assert result.disabled_by_environment is True and result.notify is False


class TestUpdateResult:
    def _result(self, **over):
        base = {
            "status": UpdateStatus.AVAILABLE,
            "mode": UpdateCheckMode.ON,
            "current": "1.0.0",
            "distribution": "pip",
            "latest": "2.0.0",
            "minimum_supported": "1.0.0",
        }
        return UpdateResult(**{**base, **over})

    def test_offer_install_only_in_on_mode(self):
        assert self._result().offer_install is True
        assert self._result(mode=UpdateCheckMode.NOTIFY_ONLY).offer_install is False

    def test_offer_install_needs_something_to_say(self):
        unknown = self._result(status=UpdateStatus.UNKNOWN, policy_update_required=True)

        assert unknown.offer_install is False
        assert self._result(status=UpdateStatus.UP_TO_DATE).offer_install is False

    def test_disabled_never_notifies(self):
        result = self._result(status=UpdateStatus.DISABLED, policy_update_required=True)

        assert result.notify is False and result.message == ""

    def test_messages(self):
        assert self._result().message == "VethuQ 2.0.0 is available (you have 1.0.0)."
        below = self._result(status=UpdateStatus.BELOW_MINIMUM, current="0.5.0").message
        assert "older than the minimum supported 1.0.0; update to 2.0.0" in below
        assert "Local features keep working" in below
        assert self._result(status=UpdateStatus.UP_TO_DATE).message == ""

    def test_to_dict_and_json(self):
        result = self._result(release_notes_url="https://n")

        data = result.to_dict()

        assert data["status"] == "available" and data["mode"] == "on"
        assert data["notify"] is True and data["message"] == result.message
        assert json.loads(result.to_json()) == data
        assert "\n" in result.to_json(indent=2)

    def test_is_frozen(self):
        with pytest.raises(AttributeError):
            self._result().status = UpdateStatus.UNKNOWN


class TestFeatureGate:
    def check(self, name="f", default=False, client="1.5.0", **features):
        policy = Policy.from_payload(PolicySigner().payload(features=features))
        return _FeatureGate.check(name, default, policy, client)

    def test_a_feature_the_policy_does_not_cover_keeps_its_default(self):
        assert self.check(default=True) == FeatureAccess("f", True)
        assert self.check(default=False) == FeatureAccess("f", False)

    def test_an_enabled_feature_is_allowed(self):
        assert self.check(f={"enabled": True}).allowed is True

    def test_a_disabled_feature_is_the_kill_switch(self):
        access = self.check(default=True, f={"enabled": False, "message": "Paused"})

        assert (access.allowed, access.message, access.requires_update) == (False, "Paused", False)

    def test_the_kill_switch_has_a_generic_message(self):
        assert "turned off" in self.check(f={"enabled": False}).message

    def test_a_feature_for_newer_clients_needs_an_update(self):
        access = self.check(f={"enabled": True, "min_client": "2.0.0"})

        assert access.allowed is False and access.requires_update is True
        assert "2.0.0" in access.message

    def test_the_policys_message_is_used_when_there_is_one(self):
        access = self.check(f={"enabled": True, "min_client": "2.0.0", "message": "Get 2.0"})

        assert access.message == "Get 2.0"

    def test_an_older_client_keeps_what_already_works(self):
        access = self.check(default=True, f={"enabled": True, "min_client": "2.0.0"})

        assert access == FeatureAccess("f", True)

    def test_an_older_client_is_not_switched_off_by_a_flag_meant_for_newer_ones(self):
        access = self.check(default=True, f={"enabled": False, "min_client": "2.0.0"})

        assert access.allowed is True

    def test_a_client_at_or_above_min_client_gets_the_flag(self):
        on = {"enabled": True, "min_client": "2.0.0"}
        off = {"enabled": False, "min_client": "2.0.0"}

        assert self.check(client="2.0.0", f=on).allowed is True
        assert self.check(client="2.0.0", f=off).allowed is False

    def test_an_unknown_client_version_is_not_held_back_by_min_client(self):
        gated = {"enabled": True, "min_client": "2.0.0"}

        assert self.check(client="unknown", f=gated).allowed is True

    def test_to_dict_and_json(self):
        access = FeatureAccess("f", False, "Needs 2", requires_update=True)

        assert access.to_dict() == {
            "name": "f",
            "allowed": False,
            "message": "Needs 2",
            "requires_update": True,
        }
        assert json.loads(access.to_json()) == access.to_dict()
