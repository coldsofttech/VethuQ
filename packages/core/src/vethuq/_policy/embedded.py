"""What this build trusts and where it looks: the policy URLs and the Ed25519 public keys.

This file is REWRITTEN BY THE BUILD (`scripts/release/embed_policy.py`); do not edit it by hand.

- `development` (what is committed): no keys, the default URLs. `refresh()` makes no request, so a
  checkout never reaches out and never trusts anything.
- `test`: the test public keys (`test-pol-...`, `test-pst-...`) and the test policy location. For
  dev and CI builds that exercise the real fetch against `policy/test/v1/`.
- `production`: the production policy and standby keys only. Release builds embed this, and
  `scripts/release/check_embedded.py` fails a release that contains anything else.

Keys are key id to unpadded base64url raw public key, as `vethuq-admin export-public` writes them.
"""

FLAVOUR = "development"

# Empty means: use the defaults in `vethuq._policy.keys`.
POLICY_URLS: tuple[str, ...] = ()

POLICY_KEYS: dict[str, str] = {}

POLICY_STANDBY_KEYS: dict[str, str] = {}
