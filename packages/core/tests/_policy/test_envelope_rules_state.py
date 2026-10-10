from __future__ import annotations

import json

import pytest

from tests.policy_factory import PolicySigner, b64url
from vethuq._policy import (
    _EnvelopeVerifier,
    _PolicyFormatError,
    _PolicyState,
    _PolicyStore,
    _RevokedKeyError,
    _RollbackError,
    _SchemaTooNewError,
    _SequenceRules,
    _SignatureError,
    _UnknownKeyError,
)


@pytest.fixture
def signer():
    return PolicySigner()


@pytest.fixture
def verifier(signer):
    return _EnvelopeVerifier(signer.keys())


class TestEnvelopeVerifier:
    def test_accepts_a_signed_envelope(self, signer, verifier):
        verified = verifier.verify(signer.signed(3))

        assert (verified.kid, verified.standby, verified.policy.sequence) == ("test-1", False, 3)
        assert json.loads(verified.payload)["sequence"] == 3

    def test_reports_a_standby_signer(self):
        standby = PolicySigner("standby-1", standby=True)

        assert _EnvelopeVerifier(standby.keys()).verify(standby.signed()).standby is True

    @pytest.mark.parametrize("raw", [b"not json", b"\xff\xfe", b"[]", b"3", b'"x"'])
    def test_garbage_is_refused(self, verifier, raw):
        with pytest.raises(_PolicyFormatError):
            verifier.verify(raw)

    def test_the_algorithm_must_be_ed25519(self, signer, verifier):
        with pytest.raises(_PolicyFormatError, match="alg"):
            verifier.verify(signer.envelope(alg="HS256"))

    @pytest.mark.parametrize("kid", [None, "", 5])
    def test_the_envelope_needs_a_key_id(self, signer, verifier, kid):
        with pytest.raises(_PolicyFormatError, match="kid"):
            verifier.verify(signer.envelope(kid=kid))

    def test_an_unknown_key_is_refused(self, signer, verifier):
        with pytest.raises(_UnknownKeyError):
            verifier.verify(signer.envelope(kid="stranger"))

    def test_a_revoked_key_is_refused(self, signer, verifier):
        with pytest.raises(_RevokedKeyError):
            verifier.verify(signer.signed(), revoked={"test-1"})

    def test_a_bad_signature_is_refused(self, signer, verifier):
        other = PolicySigner("test-1")  # same key id, different key

        with pytest.raises(_SignatureError):
            verifier.verify(other.signed())

    def test_a_changed_payload_is_refused(self, signer, verifier):
        envelope = json.loads(signer.signed(1))
        envelope["payload"] = b64url(json.dumps(signer.payload(99)).encode())

        with pytest.raises(_SignatureError):
            verifier.verify(json.dumps(envelope).encode())

    @pytest.mark.parametrize("field", ["payload", "sig"])
    @pytest.mark.parametrize("value", [None, 5, "has spaces!", "pad=="])
    def test_base64url_fields_are_checked(self, signer, verifier, field, value):
        envelope = json.loads(signer.signed())
        envelope[field] = value

        with pytest.raises(_PolicyFormatError):
            verifier.verify(json.dumps(envelope).encode())

    def test_a_short_signature_is_refused(self, signer, verifier):
        with pytest.raises(_PolicyFormatError, match="64 bytes"):
            verifier.verify(signer.envelope(sig=b64url(b"short")))

    def test_the_payload_key_id_must_match_the_envelope(self, signer, verifier):
        with pytest.raises(_PolicyFormatError, match="does not match"):
            verifier.verify(signer.envelope(signer.payload(kid="other")))

    def test_a_payload_that_is_not_json_is_refused_only_after_verification(self, signer, verifier):
        with pytest.raises(_PolicyFormatError, match="payload is not valid JSON"):
            verifier.verify(signer.envelope(b"{not json"))
        with pytest.raises(_PolicyFormatError, match="not a JSON object"):
            verifier.verify(signer.envelope(b"[1]"))

    def test_a_newer_schema_is_reported_as_too_new(self, signer, verifier):
        with pytest.raises(_SchemaTooNewError):
            verifier.verify(signer.signed(schema_version=2))

    def test_schema_below_one_is_refused(self, signer, verifier):
        with pytest.raises(_PolicyFormatError):
            verifier.verify(signer.signed(schema_version=0))

    def test_a_higher_supported_schema_can_be_set(self, signer):
        verifier = _EnvelopeVerifier(signer.keys(), supported_schema=2)

        assert verifier.verify(signer.signed(schema_version=2)).policy.schema_version == 2


class TestSequenceRules:
    @pytest.fixture
    def keys(self):
        self.a, self.b = PolicySigner("a"), PolicySigner("b")
        self.standby = PolicySigner("s", standby=True)
        return self.a.keys(self.b, self.standby)

    def verified(self, signer, sequence, keys, **over):
        return _EnvelopeVerifier(keys).verify(signer.signed(sequence, **over))

    def test_a_first_policy_needs_any_positive_sequence(self, keys):
        rules = _SequenceRules(keys)

        rules.check(self.verified(self.a, 1, keys), _PolicyState())

    def test_the_sequence_must_beat_the_floor(self, keys):
        rules = _SequenceRules(keys)
        state = _PolicyState(accepted={"a": 5})

        with pytest.raises(_RollbackError):
            rules.check(self.verified(self.a, 5, keys), state)
        rules.check(self.verified(self.a, 6, keys), state)

    def test_an_ordinary_key_is_floored_by_every_trusted_key(self, keys):
        rules = _SequenceRules(keys)
        state = _PolicyState(accepted={"a": 9})

        assert rules.floor("b", state) == 9

    def test_a_revoked_keys_sequence_stops_counting(self, keys):
        rules = _SequenceRules(keys)
        state = _PolicyState(accepted={"a": 999, "b": 3}, revoked=frozenset({"a"}))

        assert rules.floor("b", state) == 3

    def test_a_standby_key_is_floored_only_by_itself(self, keys):
        rules = _SequenceRules(keys)
        state = _PolicyState(accepted={"a": 999, "s": 2})

        assert rules.floor("s", state) == 2

    def test_a_forged_huge_sequence_cannot_block_the_standby(self, keys):
        rules = _SequenceRules(keys)
        state = _PolicyState(accepted={"a": 10**9})

        rules.check(self.verified(self.standby, 1, keys), state)

    def test_accepting_records_the_sequence_per_key(self, keys):
        rules = _SequenceRules(keys)

        state = rules.accept(self.verified(self.a, 4, keys), _PolicyState())

        assert dict(state.accepted) == {"a": 4}

    def test_only_a_standby_policy_can_revoke(self, keys):
        rules = _SequenceRules(keys)

        by_ordinary = self.verified(self.a, 1, keys, revoked_key_ids=["b"])
        by_standby = self.verified(self.standby, 1, keys, revoked_key_ids=["b"])

        ordinary = rules.accept(by_ordinary, _PolicyState())
        standby = rules.accept(by_standby, _PolicyState())

        assert ordinary.revoked == frozenset()
        assert standby.revoked == frozenset({"b"})

    def test_a_standby_cannot_revoke_itself_or_another_standby(self, keys):
        rules = _SequenceRules(keys)

        state = rules.accept(
            self.verified(self.standby, 1, keys, revoked_key_ids=["s", "a"]), _PolicyState()
        )

        assert state.revoked == frozenset({"a"})


class TestPolicyState:
    def test_a_keys_counter_never_goes_down(self):
        state = _PolicyState().with_accepted("a", 5).with_accepted("a", 3)

        assert state.accepted["a"] == 5

    def test_the_revoked_set_only_grows(self):
        state = _PolicyState().with_revoked(["a"]).with_revoked(["b"]).with_revoked([])

        assert state.revoked == frozenset({"a", "b"})

    def test_round_trips_through_json(self):
        state = _PolicyState(
            accepted={"a": 2},
            revoked=frozenset({"x"}),
            etag='"e"',
            etag_url="https://u",
            last_check=10.5,
            last_failure=2.0,
            update_required=True,
        )

        assert _PolicyState.from_json(json.loads(json.dumps(state.to_json()))) == state

    @pytest.mark.parametrize("data", [None, [], "x", 3, {}])
    def test_junk_gives_an_empty_state(self, data):
        assert _PolicyState.from_json(data) == _PolicyState()

    def test_wrong_types_are_dropped_field_by_field(self):
        state = _PolicyState.from_json(
            {
                "accepted": {"a": 1, "b": "2", "c": True, 5: 3},
                "revoked": ["x", 3],
                "etag": 7,
                "etag_url": [],
                "last_check": "soon",
                "last_failure": True,
                "update_required": "yes",
            }
        )

        assert dict(state.accepted) == {"a": 1}
        assert state.revoked == frozenset({"x"})
        assert (state.etag, state.etag_url) == (None, None)
        assert (state.last_check, state.last_failure) == (0.0, 0.0)
        assert state.update_required is False


class TestPolicyStore:
    def test_nothing_saved_reads_as_empty(self, tmp_path):
        store = _PolicyStore(tmp_path / "policy")

        assert store.read_envelope() is None
        assert store.read_state() == _PolicyState()

    def test_writes_and_reads_back(self, tmp_path):
        store = _PolicyStore(tmp_path / "policy")
        state = _PolicyState(accepted={"a": 1}, last_check=3.0)

        store.write_envelope(b'{"x": 1}')
        store.write_state(state)

        assert store.read_envelope() == b'{"x": 1}'
        assert store.read_state() == state

    def test_writes_leave_no_temp_files(self, tmp_path):
        store = _PolicyStore(tmp_path / "policy")
        store.write_envelope(b"1")
        store.write_state(_PolicyState())

        names = sorted(p.name for p in (tmp_path / "policy").iterdir())

        assert names == ["policy.json", "state.json"]

    def test_a_damaged_state_file_reads_as_empty(self, tmp_path):
        store = _PolicyStore(tmp_path)
        (tmp_path / "state.json").write_text("{not json")

        assert store.read_state() == _PolicyState()

    def test_a_folder_that_cannot_be_written_raises_oserror(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("x")

        with pytest.raises(OSError):
            _PolicyStore(blocker / "policy").write_state(_PolicyState())
