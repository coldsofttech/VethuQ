import pytest
from policy_factory import PolicySigner
from vethuq_core.policy import RollbackError
from vethuq_core.policy.envelope import EnvelopeVerifier
from vethuq_core.policy.rules import SequenceRules
from vethuq_core.policy.state import PolicyState


@pytest.fixture
def verify(keys):
    return EnvelopeVerifier(keys).verify


@pytest.fixture
def rules(keys):
    return SequenceRules(keys)


def test_lower_or_equal_sequence_is_rejected(rules, verify, signer):
    state = PolicyState(accepted={"policy-1": 5})
    with pytest.raises(RollbackError):
        rules.check(verify(signer.envelope(signer.payload(5))), state)
    with pytest.raises(RollbackError):
        rules.check(verify(signer.envelope(signer.payload(4))), state)
    rules.check(verify(signer.envelope(signer.payload(6))), state)


def test_accept_records_the_sequence_per_key(rules, verify, signer):
    state = rules.accept(verify(signer.envelope(signer.payload(7))), PolicyState())
    assert state.accepted == {"policy-1": 7}


def test_a_keys_own_counter_never_goes_down(rules, verify, signer):
    state = PolicyState(accepted={"policy-1": 9})
    assert rules.accept(verify(signer.envelope(signer.payload(3))), state).accepted["policy-1"] == 9


def test_ordinary_floor_is_the_max_over_trusted_keys(rules, verify, signer):
    state = PolicyState(accepted={"policy-1": 2, "standby-1": 10})
    with pytest.raises(RollbackError):
        rules.check(verify(signer.envelope(signer.payload(10))), state)


def test_standby_floor_is_its_own_counter_only(rules, verify, standby):
    # A forged huge sequence recorded against the active key must not block the standby.
    state = PolicyState(accepted={"policy-1": 10**9, "standby-1": 3})
    rules.check(verify(standby.envelope(standby.payload(4))), state)
    with pytest.raises(RollbackError):
        rules.check(verify(standby.envelope(standby.payload(3))), state)


def test_standby_revocation_makes_the_forged_number_stop_counting(rules, verify, signer, standby):
    state = PolicyState(accepted={"policy-1": 10**9})
    revoking = verify(standby.envelope(standby.payload(1, revoked_key_ids=["policy-1"])))
    rules.check(revoking, state)
    state = rules.accept(revoking, state)
    assert "policy-1" in state.revoked
    # The revoked key's counter no longer counts toward any floor.
    assert rules.floor("standby-1", state) == 1
    other = PolicySigner("policy-2")
    assert other.kid not in state.revoked


def test_revocation_is_ignored_unless_signed_by_a_standby_key(rules, verify, signer):
    verified = verify(signer.envelope(signer.payload(1, revoked_key_ids=["standby-1", "old"])))
    assert rules.accept(verified, PolicyState()).revoked == frozenset()


def test_standby_cannot_revoke_itself_or_another_standby(rules, verify, standby):
    verified = verify(standby.envelope(standby.payload(1, revoked_key_ids=["standby-1", "old"])))
    assert rules.accept(verified, PolicyState()).revoked == frozenset({"old"})


def test_revoked_set_only_grows(rules, verify, standby):
    state = PolicyState(revoked=frozenset({"old"}))
    verified = verify(standby.envelope(standby.payload(1, revoked_key_ids=["new"])))
    assert rules.accept(verified, state).revoked == frozenset({"old", "new"})
