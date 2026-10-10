import json

import pytest
from policy_factory import PolicySigner, b64url
from vethuq_core.policy import (
    PolicyFormatError,
    PolicyKeys,
    RevokedKeyError,
    SchemaTooNewError,
    SignatureError,
    UnknownKeyError,
)
from vethuq_core.policy.envelope import EnvelopeVerifier


@pytest.fixture
def verifier(keys):
    return EnvelopeVerifier(keys)


def test_valid_envelope_verifies(verifier, signer):
    verified = verifier.verify(signer.envelope(signer.payload(3, extra_field={"x": 1})))
    assert verified.kid == "policy-1"
    assert not verified.standby
    assert verified.policy.sequence == 3
    assert verified.policy.versions["pip"].latest == "1.2.0"
    assert verified.policy.raw["extra_field"] == {"x": 1}  # unknown fields are kept, not fatal


def test_bad_signature_is_rejected(verifier, signer):
    other = PolicySigner("policy-1")  # same kid, different private key
    with pytest.raises(SignatureError):
        verifier.verify(other.envelope())


def test_tampered_payload_is_rejected(verifier, signer):
    good = json.loads(signer.envelope())
    forged = signer.payload(99)
    good["payload"] = b64url(json.dumps(forged).encode())
    with pytest.raises(SignatureError):
        verifier.verify(json.dumps(good).encode())


def test_unknown_kid_is_rejected(verifier):
    stranger = PolicySigner("stranger")
    with pytest.raises(UnknownKeyError):
        verifier.verify(stranger.envelope())


def test_revoked_kid_is_rejected(verifier, signer):
    with pytest.raises(RevokedKeyError):
        verifier.verify(signer.envelope(), revoked={"policy-1"})


def test_payload_kid_must_match_envelope_kid(verifier, signer, standby):
    payload = signer.payload()
    payload["kid"] = "standby-1"
    with pytest.raises(PolicyFormatError):
        verifier.verify(signer.envelope(payload))


def test_wrong_algorithm_is_rejected(verifier, signer):
    with pytest.raises(PolicyFormatError):
        verifier.verify(signer.envelope(alg="RS256"))


def test_higher_schema_major_is_reported_after_verification(verifier, signer):
    with pytest.raises(SchemaTooNewError):
        verifier.verify(signer.envelope(signer.payload(schema_version=2)))


def test_higher_schema_with_bad_signature_is_a_signature_error(verifier, signer):
    forged = json.loads(signer.envelope(signer.payload(schema_version=2)))
    forged["sig"] = b64url(bytes(64))
    with pytest.raises(SignatureError):
        verifier.verify(json.dumps(forged).encode())


@pytest.mark.parametrize("raw", [b"", b"not json", b"[]", b'{"alg":"Ed25519"}', b"\xff\xfe"])
def test_malformed_envelopes_are_rejected(verifier, raw):
    with pytest.raises(PolicyFormatError):
        verifier.verify(raw)


@pytest.mark.parametrize("field", ["payload", "sig"])
@pytest.mark.parametrize("value", ["not base64!", "abc=", 5, None])
def test_malformed_base64url_is_rejected(verifier, signer, field, value):
    with pytest.raises(PolicyFormatError):
        verifier.verify(signer.envelope(**{field: value}))


def test_short_signature_is_rejected(verifier, signer):
    with pytest.raises(PolicyFormatError):
        verifier.verify(signer.envelope(sig=b64url(b"short")))


def test_missing_versions_is_rejected(verifier, signer):
    payload = signer.payload()
    del payload["versions"]
    with pytest.raises(PolicyFormatError):
        verifier.verify(signer.envelope(payload))


def test_no_embedded_keys_means_everything_is_unknown(signer):
    with pytest.raises(UnknownKeyError):
        EnvelopeVerifier(PolicyKeys.embedded()).verify(signer.envelope())
