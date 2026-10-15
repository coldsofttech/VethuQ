# Policy contract fixtures

Signed policy envelopes for every way a policy can be good or bad, shared by the core client's contract
tests (`packages/core/tests/_policy/test_contract_fixtures.py`) and the admin tool's tests
(`VethuQ-entitlements`: `packages/admin/tests/test_core_contract_fixtures.py`).

- `v1/manifest.json` lists each file and what a client must do with it (`accepted`, `rejected`,
  `update_required`), plus the cases that cannot be static files (oversize body, offline, unchanged ETag).
- They are signed with a **test** key derived from a fixed phrase in `tools/policy/make_fixtures.py`; only its
  public half is here (`v1/keys/contract-test-1.pub`). It is not, and must never be, a production key.
- Regenerate with `python tools/policy/make_fixtures.py`; CI runs it with `--check`, and the core tests fail
  if the files are stale.
- The admin tests read this folder from `VETHUQ_POLICY_FIXTURES`, or from a `VethuQ` checkout next to the
  entitlements checkout, and are skipped when neither exists.
