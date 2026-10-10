# Signed envelope (v1)

`/v1/policy.json` is a signed envelope, not the bare payload. Schema:
[`schema/v1/envelope.schema.json`](../schema/v1/envelope.schema.json).

```json
{
  "alg": "Ed25519",
  "kid": "example-1",
  "payload": "<base64url of the exact payload bytes>",
  "sig": "<base64url of the 64-byte Ed25519 signature>"
}
```

| Field | Description |
|---|---|
| `alg` | Always `Ed25519`. |
| `kid` | Id of the signing key. Selects the public key the client verifies with; must equal `payload.kid`. |
| `payload` | base64url (RFC 4648 section 5, **no padding**) of the exact UTF-8 bytes of the payload JSON. |
| `sig` | base64url (no padding) of the Ed25519 signature (64 bytes, 86 characters) over the **decoded payload bytes**. |

## Why the payload is a string

The signature covers exact bytes. Carrying the payload as base64url means no party ever has to
re-serialise JSON (key order, whitespace, number formatting) to verify it.

## Signing (admin tool)

1. Build the payload JSON, validate it against `policy.schema.json`, serialise to UTF-8 bytes.
2. `sig = Ed25519_sign(private_key, bytes)`.
3. Write the envelope with `payload = base64url(bytes)`, `sig = base64url(sig)`, `kid` of the key used.

## Verification (client)

1. Parse the envelope; require `alg == "Ed25519"`.
2. Look up the embedded public key for `kid`; unknown `kid` means reject. Reject too if `kid` is in
   the persisted revoked set (see [Key revocation](schema-v1.md#key-revocation)).
3. base64url-decode `payload` and `sig`; verify the signature over the payload bytes. Reject on failure.
4. **Only after** verification, parse the payload; require `payload.kid == kid` and `schema_version == 1`.
5. Reject if `sequence` is not greater than the **floor for this `kid`** (see
   [Rollback protection](#rollback-protection-and-forged-sequences)); then apply the policy and record
   the sequence against `kid`.
6. If `kid` is in the client's embedded **policy-standby** set, add `payload.revoked_key_ids` to the
   persisted revoked set (ignoring any entry that is `kid` itself or a standby key). From then on
   refuse anything signed by those key ids: policies, licences and bundle manifests.

## Rollback protection and forged sequences

`sequence` stops an old policy being replayed. A single "last accepted sequence" would let a
compromised signing key do harm: it could sign one policy with a huge `sequence`, and a client that
accepted it would then reject every legitimate policy below that number (#266). So the client keeps
the highest sequence accepted **per signing key id** and derives a floor from the keys it still
trusts:

1. **Record per key.** After accepting a policy, store `accepted[kid] = max(accepted[kid], sequence)`
   (persisted with the revoked set, atomically).
2. **Floor for an ordinary key** (a key in the embedded policy set that is not a standby):
   the maximum of `accepted[k]` over every key `k` that is **currently trusted and not revoked**.
   A sequence recorded from a key that has been revoked, or dropped by a client release, no longer
   counts. Reject a policy whose `sequence` is not greater than this floor.
3. **Floor for a standby key** (a key in the embedded policy-standby set): that key's own
   `accepted[kid]`, nothing else. The standby is the recovery path, so a forged number from another
   key cannot block it. A standby-signed policy may carry `revoked_key_ids`
   ([Key revocation](schema-v1.md#key-revocation-revoked_key_ids)); once accepted, the revoked keys
   stop counting towards every floor.
4. **A client release that drops a key** has the same effect: that key's entry is ignored from then
   on. No client ever needs to "reset" a counter by hand.
5. An identical re-fetch of the policy already applied is simply ignored.

What this gives:

- A forged high sequence from a compromised key blocks only policies from that key (and ordinary
  keys while it is still trusted). The standby can revoke it, with an ordinary sequence just above
  the standby's own last, **without guessing the attacker's number**.
- After the revocation the forged number stops counting, and ordinary keys resume from the highest
  sequence of keys that are still trusted.
- Old policies stay unreplayable per key: a key's own counter never goes down.

Known residual window: a policy signed by a standby key that this client never saw, with a
sequence above that standby's last, is accepted even if a newer ordinary policy exists. That
standby signs rarely and every policy it signs is issued deliberately; the replay needs an old,
standby-signed file whose sequence the client has not yet passed.

Considered and not adopted: refusing "implausible" jumps above the floor. An attacker can stay under
any fixed limit and raise the floor step by step, and the publisher legitimately needs large jumps
(`policy sign --sequence`) in some procedures. The per-key floor removes the cause instead.

## Example

[`examples/v1/envelope.example.json`](../examples/v1/envelope.example.json) wraps the minimal payload.
Its `sig` is 64 zero bytes and its `kid` is fictional, so **it does not verify** against any key. It
only demonstrates the format. Real signed output comes from the admin CLI.
