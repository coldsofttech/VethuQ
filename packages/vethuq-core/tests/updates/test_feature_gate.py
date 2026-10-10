import pytest
from policy_factory import PolicySigner
from vethuq_core.policy import Policy
from vethuq_core.updates import FeatureGate


def policy(**features):
    return Policy.from_payload(PolicySigner("k").payload(1, kid="k", features=features))


def gate(name, default, features, client="1.0.0"):
    return FeatureGate.check(name, default, policy(**features), client)


def test_absent_flag_uses_the_builtin_default():
    assert gate("cloud", True, {}).allowed is True
    access = gate("cloud", False, {})
    assert access.allowed is False and access.message is None


def test_enabled_for_a_new_enough_client():
    access = gate("cloud", False, {"cloud": {"enabled": True, "min_client": "1.2.0"}}, "1.2.0")
    assert access.allowed is True and access.message is None


def test_held_back_for_an_old_client_with_the_policy_message():
    features = {"cloud": {"enabled": True, "min_client": "1.2.0", "message": "Needs 1.2.0."}}
    access = gate("cloud", False, features, "1.0.0")
    assert (access.allowed, access.requires_update, access.message) == (False, True, "Needs 1.2.0.")


def test_held_back_for_an_old_client_with_a_generic_message():
    access = gate("cloud", False, {"cloud": {"enabled": True, "min_client": "1.2.0"}}, "1.0.0")
    assert access.requires_update and "1.2.0" in access.message


def test_old_client_keeps_a_default_that_is_already_on():
    access = gate("cloud", True, {"cloud": {"enabled": True, "min_client": "1.2.0"}}, "1.0.0")
    assert access.allowed is True and not access.requires_update


def test_kill_switch():
    access = gate("cloud", True, {"cloud": {"enabled": False, "message": "Paused."}})
    assert (access.allowed, access.requires_update, access.message) == (False, False, "Paused.")
    assert gate("cloud", True, {"cloud": {"enabled": False}}).message


def test_kill_switch_does_not_apply_to_clients_below_min_client():
    features = {"cloud": {"enabled": False, "min_client": "2.0.0"}}
    assert gate("cloud", True, features, "1.0.0").allowed is True


@pytest.mark.parametrize("client", ["unknown", ""])
def test_unparseable_client_version_is_treated_as_new_enough(client):
    features = {"cloud": {"enabled": True, "min_client": "1.2.0"}}
    assert gate("cloud", False, features, client).allowed is True


def test_never_raises(monkeypatch):
    monkeypatch.setattr(
        "vethuq_core.updates.features.PolicyService.current",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broken")),
    )
    assert FeatureGate.check("cloud", True).allowed is True
