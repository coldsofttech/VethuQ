#!/usr/bin/env python3
"""Regenerate the policy contract fixtures in `policy/fixtures/v1/`.

The fixtures are signed envelopes covering every way a policy can be good or bad. They are signed
with a TEST key derived from a fixed phrase, so the output is reproducible and the private key is
never stored; only its public half is published here (`keys/<kid>.pub`). Production
keys never appear in this directory.

The core client's contract tests and the admin tool's signing tests both read `manifest.json`:
each entry names a fixture file, what the client must do with it (`expect`) and whether the signed
policy it holds is acceptable. Cases that cannot be a static file (an oversize body, being offline,
an unchanged ETag) are listed under `generated` so both sides cover them the same way.

    python tools/policy/make_fixtures.py          # rewrite the fixtures
    python tools/policy/make_fixtures.py --check  # fail if they are out of date
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

OUT = Path(__file__).resolve().parents[2] / "policy" / "fixtures" / "v1"
UNKNOWN_KID = "contract-unknown"
SEED = hashlib.sha256(b"vethuq policy contract fixtures: test key, not a secret").digest()
STANDBY_SEED = hashlib.sha256(b"vethuq policy contract fixtures: standby test key").digest()
OTHER_SEED = hashlib.sha256(b"vethuq policy contract fixtures: signer nobody trusts").digest()


def public_of(seed: bytes) -> bytes:
    return (
        Ed25519PrivateKey.from_private_bytes(seed)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def kid_of(prefix: str, seed: bytes) -> str:
    """The id scheme the admin tool uses: the role prefix and 16 hex digits of SHA-256(key)."""
    return f"test-{prefix}-{hashlib.sha256(public_of(seed)).hexdigest()[:16]}"


KID = kid_of("pol", SEED)  # the current policy key
STANDBY_KID = kid_of("pst", STANDBY_SEED)  # the policy-standby key: the only one that can revoke
LICENCE_KID = "test-lic-00000000000000aa"  # a signing key id for a revocation to name


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def payload(sequence: int, kid: str = KID, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "sequence": sequence,
        "issued_at": "2026-10-01T12:00:00Z",
        "kid": kid,
        "versions": {
            "desktop": {"latest": "2.0.0", "minimum_supported": "1.0.0"},
            "pip": {"latest": "2.0.0", "minimum_supported": "1.0.0"},
        },
    }
    data.update(over)
    return data


def envelope(body: dict[str, Any] | bytes, seed: bytes = SEED, kid: str = KID, **over: Any) -> str:
    raw = body if isinstance(body, bytes) else json.dumps(body, sort_keys=True).encode()
    key = Ed25519PrivateKey.from_private_bytes(seed)
    data = {"alg": "Ed25519", "kid": kid, "payload": b64url(raw), "sig": b64url(key.sign(raw))}
    data.update(over)
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def build() -> dict[str, str]:
    notices = [
        {"id": "active", "message": "Active now.", "severity": "info"},
        {
            "id": "expired",
            "message": "Over.",
            "severity": "info",
            "starts_at": "2020-01-01T00:00:00Z",
            "ends_at": "2020-01-02T00:00:00Z",
        },
        {
            "id": "future",
            "message": "Not yet.",
            "severity": "warning",
            "starts_at": "2099-01-01T00:00:00Z",
        },
    ]
    good = envelope(payload(5, notices=notices))
    tampered = json.loads(envelope(payload(6)))
    tampered["sig"] = b64url(bytes(64))
    files = {
        "valid.envelope.json": good,
        "valid-newer.envelope.json": envelope(payload(6, notices=notices)),
        "bad-signature.envelope.json": json.dumps(tampered, indent=2, sort_keys=True) + "\n",
        "wrong-signer.envelope.json": envelope(payload(7), seed=OTHER_SEED),
        "unknown-key-id.envelope.json": envelope(
            payload(7, kid=UNKNOWN_KID), seed=OTHER_SEED, kid=UNKNOWN_KID
        ),
        "lower-sequence.envelope.json": envelope(payload(4)),
        "higher-schema-major.envelope.json": envelope(payload(9, schema_version=2)),
        "unknown-fields.envelope.json": envelope(
            payload(8, future_section={"x": 1}, notices=[{**notices[0], "future_field": True}])
        ),
        "malformed-json.envelope.json": '{"alg": "Ed25519", "kid": \n',
        "payload-not-json.envelope.json": envelope(b"this is not json"),
    }
    files |= {
        # The standby key revokes the current key. Everything the current key signs is refused
        # from then on, whatever its sequence.
        "revoke-by-standby.envelope.json": envelope(
            payload(20, STANDBY_KID, revoked_key_ids=[KID]), STANDBY_SEED, STANDBY_KID
        ),
        "signed-by-revoked-key.envelope.json": envelope(payload(30)),
        # A revocation signed by the current (non-standby) key has no authority.
        "revoke-by-active.envelope.json": envelope(payload(7, revoked_key_ids=[LICENCE_KID])),
        # Entries naming the signer or a standby key are ignored; the other entry stands.
        "revoke-ignored-entries.envelope.json": envelope(
            payload(21, STANDBY_KID, revoked_key_ids=[STANDBY_KID, LICENCE_KID]),
            STANDBY_SEED,
            STANDBY_KID,
        ),
    }
    files[f"keys/{KID}.pub"] = b64url(public_of(SEED)) + "\n"
    files[f"keys/{STANDBY_KID}.pub"] = b64url(public_of(STANDBY_SEED)) + "\n"
    manifest = {
        "kid": KID,
        "standby_kid": STANDBY_KID,
        "note": "Test key only. 'last_good' is valid.envelope.json (sequence 5).",
        "fixtures": [
            {"file": "valid.envelope.json", "expect": "accepted", "sequence": 5},
            {"file": "valid-newer.envelope.json", "expect": "accepted", "sequence": 6},
            {"file": "unknown-fields.envelope.json", "expect": "accepted", "sequence": 8},
            {"file": "bad-signature.envelope.json", "expect": "rejected"},
            {"file": "wrong-signer.envelope.json", "expect": "rejected"},
            {"file": "unknown-key-id.envelope.json", "expect": "rejected"},
            {"file": "lower-sequence.envelope.json", "expect": "rejected", "reason": "downgrade"},
            {"file": "higher-schema-major.envelope.json", "expect": "update_required"},
            {"file": "malformed-json.envelope.json", "expect": "rejected"},
            {"file": "payload-not-json.envelope.json", "expect": "rejected"},
        ],
        "notice_windows": {
            "file": "valid.envelope.json",
            "active": ["active"],
            "expired": ["expired"],
            "future": ["future"],
        },
        "revocation": {
            "revoked_by_standby": {
                "file": "revoke-by-standby.envelope.json",
                "sequence": 20,
                "revokes": [KID],
            },
            "refused_once_revoked": [
                "signed-by-revoked-key.envelope.json",
                "valid-newer.envelope.json",
            ],
            "no_authority": {
                "file": "revoke-by-active.envelope.json",
                "sequence": 7,
                "ignored": [LICENCE_KID],
            },
            "ignored_entries": {
                "file": "revoke-ignored-entries.envelope.json",
                "sequence": 21,
                "ignored": [STANDBY_KID],
                "revokes": [LICENCE_KID],
            },
        },
        "generated": ["oversize payload", "all URLs failing / offline", "ETag unchanged"],
    }
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the files are out of date")
    args = parser.parse_args()
    stale = []
    for name, text in build().items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        print("out of date: " + ", ".join(stale) + "\nrun: python tools/policy/make_fixtures.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
