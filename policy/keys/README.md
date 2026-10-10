# Published public keys

One file per signing key id: `keys/<kid>.pub`, containing the **raw 32-byte Ed25519 public key**
encoded as base64url without padding (single line). The filename (minus `.pub`) is the `kid`
used in the envelope.

CI verifies `v1/policy.json` against these keys. Only public keys belong here. Never commit private
keys. Rotating a key means adding a new `<kid>.pub`; keep old ones as long as old signed files must verify.

No key is published yet; it is added when the admin tooling generates the first signing key.
