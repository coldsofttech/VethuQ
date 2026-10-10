from datetime import UTC, datetime

from policy_factory import PolicySigner
from vethuq_core.policy import Baseline, Policy


def parse(**extra):
    return Policy.from_payload(PolicySigner("k").payload(1, kid="k", **extra))


def test_baseline_is_zero_versions_and_empty():
    policy = Baseline.policy()
    assert policy.sequence == 0
    assert policy.versions["desktop"].latest == "0.0.0"
    assert policy.versions["pip"].minimum_supported == "0.0.0"
    assert policy.notices == () and policy.features == {}


def test_notice_window_and_malformed_entries():
    policy = parse(
        notices=[
            {
                "id": "a",
                "message": "hi",
                "starts_at": "2026-10-01T00:00:00Z",
                "ends_at": "2026-10-31T00:00:00Z",
            },
            {"id": "b", "message": "later", "starts_at": "2030-01-01T00:00:00Z"},
            {"id": "c"},  # no message: skipped
            "junk",
        ]
    )
    active = policy.active_notices(datetime(2026, 10, 10, tzinfo=UTC))
    assert [n.id for n in active] == ["a"]
    assert [n.id for n in policy.notices] == ["a", "b"]


def test_feature_flags_default_and_min_client():
    policy = parse(features={"github_tier": {"enabled": False, "min_client": "1.0.0"}})
    assert policy.is_enabled("github_tier", True, "1.2.0") is False
    assert policy.is_enabled("github_tier", True, "0.9.0") is True  # flag does not apply yet
    assert policy.is_enabled("absent", True) is True


def test_revoked_ids_are_deduplicated_and_typed():
    assert parse(revoked_key_ids=["a", "a", 5, "b"]).revoked_key_ids == ("a", "b")


def test_feature_message_is_kept_when_it_is_text():
    policy = parse(
        features={
            "a": {"enabled": True, "min_client": "1.2.0", "message": "Needs 1.2.0."},
            "b": {"enabled": True, "message": 5},
            "c": {"enabled": True},
        }
    )
    assert policy.features["a"].message == "Needs 1.2.0."
    assert policy.features["b"].message is None
    assert policy.features["c"].message is None
