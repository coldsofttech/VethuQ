from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tests.policy_factory import PolicySigner, b64url
from vethuq._policy import (
    Policy,
    PolicyResult,
    _Baseline,
    _PolicyFormatError,
    _PolicyKey,
    _PolicyKeys,
    _PolicyUrls,
)
from vethuq.enums import PolicySource, PolicyStatus


class TestPolicyKey:
    def test_reads_a_published_key_file(self):
        raw = bytes(range(32))

        key = _PolicyKey.from_b64url("k1", b64url(raw) + "\n", standby=True)

        assert (key.kid, key.public_key, key.standby) == ("k1", raw, True)

    @pytest.mark.parametrize("text", ["!!!", b64url(b"short"), ""])
    def test_a_bad_key_is_refused(self, text):
        with pytest.raises(_PolicyFormatError):
            _PolicyKey.from_b64url("k1", text)


class TestPolicyKeys:
    def test_lookup_and_standby(self):
        a, b = PolicySigner("a"), PolicySigner("b", standby=True)
        keys = a.keys(b)

        assert keys.kids == ("a", "b")
        assert keys.get("a") == a.key and keys.get("zzz") is None
        assert keys.standby_kids == frozenset({"b"})
        assert keys.is_standby("b") and not keys.is_standby("a") and not keys.is_standby("zzz")

    def test_no_production_keys_are_built_in_yet(self):
        assert _PolicyKeys.EMBEDDED == ()
        assert _PolicyKeys.embedded().kids == ()


class TestPolicyUrls:
    def test_defaults_are_the_pages_url_then_two_mirrors(self):
        assert _PolicyUrls.resolve({}) == (
            "https://coldsofttech.github.io/vethuq/policy/v1/policy.json",
            "https://cdn.jsdelivr.net/gh/coldsofttech/vethuq@main/policy/v1/policy.json",
            "https://raw.githubusercontent.com/coldsofttech/vethuq/main/policy/v1/policy.json",
        )

    def test_every_default_is_https_and_ends_in_the_policy_file(self):
        for url in _PolicyUrls.DEFAULT:
            assert url.startswith("https://") and url.endswith("/policy/v1/policy.json")

    def test_the_environment_replaces_them(self):
        env = {"VETHUQ_POLICY_URLS": "https://a.example/p.json, https://b.example/p.json"}

        assert _PolicyUrls.resolve(env) == ("https://a.example/p.json", "https://b.example/p.json")

    def test_only_well_formed_https_urls_count_and_repeats_are_dropped(self):
        listed = "http://x/p.json ftp://y not-a-url https://ok/p.json https://ok/p.json"
        env = {"VETHUQ_POLICY_URLS": listed}

        assert _PolicyUrls.resolve(env) == ("https://ok/p.json",)

    @pytest.mark.parametrize("value", ["", "   ", "http://x/p.json", "junk"])
    def test_nothing_usable_falls_back_to_the_defaults(self, value):
        assert _PolicyUrls.resolve({"VETHUQ_POLICY_URLS": value}) == _PolicyUrls.DEFAULT

    def test_reads_the_process_environment_by_default(self, monkeypatch):
        monkeypatch.setenv("VETHUQ_POLICY_URLS", "https://env.example/p.json")

        assert _PolicyUrls.resolve() == ("https://env.example/p.json",)


class TestPolicyModel:
    @pytest.fixture
    def signer(self):
        return PolicySigner()

    def test_parses_the_required_fields(self, signer):
        policy = Policy.from_payload(signer.payload(7))

        assert (policy.schema_version, policy.sequence, policy.kid) == (1, 7, "test-1")
        assert policy.issued_at == datetime(2026, 10, 1, 12, tzinfo=UTC)
        assert policy.versions["pip"].latest == "2.0.0"
        assert policy.versions["pip"].minimum_supported == "1.0.0"
        assert policy.versions["pip"].release_notes_url == "https://example.com/notes"
        assert policy.versions["desktop"].release_notes_url is None

    def test_a_time_without_a_zone_is_utc(self, signer):
        policy = Policy.from_payload(signer.payload(issued_at="2026-10-01T12:00:00"))

        assert policy.issued_at.tzinfo is UTC

    @pytest.mark.parametrize(
        "over",
        [
            {"sequence": 0},
            {"sequence": True},
            {"sequence": "1"},
            {"schema_version": "1"},
            {"kid": ""},
            {"issued_at": 5},
            {"issued_at": "yesterday"},
            {"versions": []},
            {"versions": {"pip": {"latest": "1.0.0"}}},
        ],
    )
    def test_malformed_required_fields_are_refused(self, signer, over):
        with pytest.raises(_PolicyFormatError):
            Policy.from_payload(signer.payload(**over))

    def test_unknown_fields_are_ignored_but_kept_in_raw(self, signer):
        policy = Policy.from_payload(signer.payload(rate_card={"x": 1}, surprise=True))

        assert policy.raw["rate_card"] == {"x": 1} and policy.raw["surprise"] is True

    def test_notices(self, signer):
        policy = Policy.from_payload(
            signer.payload(
                notices=[
                    {"id": "a", "message": "hello", "severity": "warning", "link": "https://x"},
                    {"id": "b"},  # no message: skipped
                    {"message": "no id"},  # skipped
                    "junk",
                    {"id": "c", "message": "bad time", "starts_at": "never"},  # skipped
                ]
            )
        )

        assert [n.id for n in policy.notices] == ["a"]
        assert policy.notices[0].severity == "warning" and policy.notices[0].link == "https://x"

    def test_only_notices_inside_their_window_are_active(self, signer):
        policy = Policy.from_payload(
            signer.payload(
                notices=[
                    {"id": "always", "message": "m"},
                    {"id": "future", "message": "m", "starts_at": "2026-12-01T00:00:00Z"},
                    {"id": "past", "message": "m", "ends_at": "2026-01-01T00:00:00Z"},
                    {
                        "id": "now",
                        "message": "m",
                        "starts_at": "2026-10-01T00:00:00Z",
                        "ends_at": "2026-11-01T00:00:00Z",
                    },
                ]
            )
        )

        at = datetime(2026, 10, 15, tzinfo=UTC)

        assert [n.id for n in policy.active_notices(at)] == ["always", "now"]

    def test_active_notices_default_to_now(self, signer):
        policy = Policy.from_payload(signer.payload(notices=[{"id": "a", "message": "m"}]))

        assert len(policy.active_notices()) == 1

    def test_features(self, signer):
        policy = Policy.from_payload(
            signer.payload(
                features={
                    "on": {"enabled": True},
                    "gated": {"enabled": True, "min_client": "2.0.0", "message": "Needs 2"},
                    "bad": {"enabled": "yes"},
                    "junk": 3,
                }
            )
        )

        assert set(policy.features) == {"on", "gated"}
        assert policy.features["gated"].min_client == "2.0.0"
        assert policy.features["gated"].message == "Needs 2"
        assert policy.features["on"].min_client is None

    def test_revoked_key_ids_are_deduplicated_and_typed(self, signer):
        policy = Policy.from_payload(signer.payload(revoked_key_ids=["a", "a", 3, "b"]))

        assert policy.revoked_key_ids == ("a", "b")

    def test_to_dict_and_json_give_the_signed_payload(self, signer):
        payload = signer.payload(5, extra=1)
        policy = Policy.from_payload(payload)

        assert policy.to_dict() == payload
        assert json.loads(policy.to_json()) == payload
        assert "\n" in policy.to_json(indent=2)


class TestBaseline:
    def test_is_sequence_zero_with_no_versions_news_or_features(self):
        policy = _Baseline.policy()

        assert policy.sequence == 0 and policy.kid == "baseline"
        assert policy.versions["pip"].latest == "0.0.0"
        assert policy.versions["desktop"].minimum_supported == "0.0.0"
        assert policy.notices == () and dict(policy.features) == {}


class TestPolicyResult:
    def test_to_dict_and_json(self):
        result = PolicyResult(_Baseline.policy(), PolicySource.BASELINE, PolicyStatus.CURRENT)

        assert result.to_dict() == {
            "source": "baseline",
            "status": "current",
            "detail": "",
            "update_required": False,
            "sequence": 0,
            "kid": "baseline",
        }
        assert json.loads(result.to_json()) == result.to_dict()

    def test_the_update_message(self):
        assert PolicyResult.UPDATE_MESSAGE == "Update VethuQ to receive new policy."
