# Policy client

`vethuq_core.policy` lets every distribution (CLI, desktop app, `vethuq` pip package) learn from
a signed `policy.json` without a reinstall. It fetches the policy, verifies its Ed25519
signature, caches it, and falls back to a built-in baseline. The policy itself, its schema and
the signing format live in the `vethuq-policy` repository
(`docs/schema-v1.md`, `docs/envelope.md`, `docs/hosting-and-mirrors.md`); this page covers the
client.

## Guarantees

- **No network on import.** `import vethuq_core.policy` does no I/O. Only
  `PolicyClient.refresh()` fetches, and only when asked.
- **Never blocks, never raises.** `refresh()` and `current()` return a `PolicyResult` whatever
  happens: offline, every URL failing, a bad signature, a damaged cache, a read-only data folder.
  `refresh_in_background()` runs the same call on a daemon thread, so startup is never delayed.
- **Last good policy wins.** On any failure the client keeps the last accepted policy; with none
  it uses the baseline.
- **Unknown fields are ignored.** The whole verified payload stays available in `Policy.raw`, so
  sections not modelled yet (credit rates, limits, promotions) can be read without a client change.

## Using it

```python
from vethuq_core.policy import PolicyClient

client = PolicyClient()

result = client.current()            # cached policy or baseline; no network
result = client.refresh()            # at most about once a day; never raises
client.refresh_in_background()       # same, on a daemon thread
client.refresh(force=True)           # ignore the once-a-day gate

policy = result.policy
policy.versions["pip"].latest        # "0.0.0" until a signed policy is accepted
policy.active_notices()
policy.is_enabled("github_tier", default=True, client_version="1.0.0")
if result.update_required:
    print(result.detail)             # "Update VethuQ to receive new policy."
```

`PolicyResult` carries:

| Field | Meaning |
|---|---|
| `policy` | The `Policy` to use |
| `source` | `fetched` (accepted by this call), `cache` (the last accepted policy, re-verified from disk) or `baseline` |
| `status` | `current`, `updated`, `unchanged`, `skipped`, `offline`, `rejected` or `update_required` |
| `detail` | Why a fetch failed or was refused, for logs; the update message when `update_required` |
| `update_required` | The latest policy needs a newer VethuQ than this one |

## Where it runs

| Distribution | What it does |
|---|---|
| CLI (`vethuq`) | Every command starts `PolicyService.start()` after logging is set up (background thread). `vethuq policy show` / `refresh` show the policy and force a check. |
| Desktop app | `MainWindow` starts the same background refresh once the database is open. Settings > About lists the policy in use (sequence, baseline, or the update message). |
| `vethuq` package (library) | Nothing runs on `import vethuq` or `Vethuq()`. `client.policy.current()` reads the saved policy; `client.policy.refresh()` is the only call that uses the network. The pip CLI is the CLI above. |

`PolicyService` (in `service.py`) holds the one shared client per process and passes the CLI's or
the app's logger to it, so policy messages land in `cli.log` / `ui.log`. While no production keys
are embedded, `refresh()` returns `skipped` without any request.

## Baseline

Until a policy is accepted, and when none can be used, the client uses a built-in policy:
sequence 0, `desktop` and `pip` at `0.0.0` (latest and minimum), no notices and no features.
Any signed policy (sequence 1 or higher) supersedes it.

## Fetching

- URLs come from `PolicyUrls.DEFAULT`, tried in order: GitHub Pages, then the jsDelivr and raw
  GitHub mirrors. Trust comes from the signature, not the host.
- Each request has a 2.5 s timeout, a 5 s total limit and a 256 KiB size cap. Only `https` URLs
  are used.
- Conditional requests: the ETag of the last accepted response is sent as `If-None-Match`, only to
  the URL it came from. A 304 counts as "nothing newer".
- The first URL that returns a verified, acceptable policy wins. Network errors, non-200
  responses and rejected policies fall through to the next URL.
- At most one check a day. After a failed check the client retries after an hour.

## Verification

In this order, using the keys embedded in the client (`PolicyKeys.EMBEDDED`):

1. `alg` must be `Ed25519`.
2. The `kid` must be one of the embedded keys and not in the persisted revoked set.
3. The signature must verify over the decoded payload bytes.
4. Only then is the payload parsed. Its `kid` must equal the envelope's, and `schema_version`
   must not exceed what this client supports.
5. The `sequence` must be above the floor for the signing key (below).

Anything else is rejected and the previous policy stays in use. A cached policy is verified
again every time it is loaded, so a tampered or newly revoked cache is not trusted.

## Downgrade protection and revocation

The highest accepted `sequence` is kept per signing key id.

- An ordinary key must exceed the highest sequence recorded for any key that is still trusted and
  not revoked.
- A standby key must exceed only its own last sequence, so a forged huge sequence from a
  compromised key can't block the recovery policy.
- A policy signed by a standby key may carry `revoked_key_ids`. They are added to a persisted,
  grow-only set (never the signer itself or a standby key) and are refused from then on; their
  sequences stop counting toward any floor. A revocation in a policy signed by an ordinary key is
  ignored.
- An identical re-fetch of the policy already applied is "unchanged", not a rollback.

## Higher schema versions

If a correctly signed policy has a higher schema major than this client supports, the client
keeps the last compatible policy, records `update_required`, and reports
"Update VethuQ to receive new policy." (`PolicyResult.UPDATE_MESSAGE`). A later compatible policy
clears it.

## What is stored

In `<data root>/policy/` (the data root is `Paths.default_data_root()`; the folder is disposable,
and a damaged or missing file just means "never fetched"):

| File | Contents |
|---|---|
| `policy.json` | The last accepted envelope, exactly as served |
| `state.json` | Accepted sequence per key id, revoked key ids, ETag and its URL, last check and last failure times, `update_required` |

Both are written atomically (temp file, flush, replace). If the folder is not writable the
fetched policy is still returned for the session and `detail` says it was not cached.

## Embedded keys

`PolicyKeys.EMBEDDED` is empty until the production keys exist
(coldsofttech/VethuQ-support#275): the current key and the standby key, added as
`PolicyKey.from_b64url(kid, "<contents of keys/<kid>.pub>", standby=...)`. With no keys every
envelope is rejected as unknown and the baseline stays in use. Tests build their own keys with
`PolicySigner` in `packages/vethuq-core/tests/policy_factory.py`.

## Code map

| Module | Class | Role |
|---|---|---|
| `keys.py` | `PolicyKey`, `PolicyKeys`, `PolicyUrls` | Embedded public keys and URL list |
| `envelope.py` | `EnvelopeVerifier`, `VerifiedEnvelope` | Parse and verify the signed envelope |
| `model.py` | `Policy`, `DistributionVersions`, `Notice`, `Feature` | The parsed policy |
| `baseline.py` | `Baseline` | The built-in fallback |
| `rules.py` | `SequenceRules` | Sequence floors and key revocation |
| `state.py` | `PolicyState`, `PolicyStore` | Persisted state, atomic writes |
| `fetch.py` | `PolicyFetcher` | HTTPS fetch: timeout, size cap, ETag, URL fall-through |
| `client.py` | `PolicyClient`, `PolicyResult` | Ties it together; the public entry point |
| `service.py` | `PolicyService` | The shared client and how the front ends start it |
| `errors.py` | `PolicyError` and subclasses | Why a policy was refused |
