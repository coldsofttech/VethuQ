# VethuQ policy

The public, static home of the signed **`policy.json`** that VethuQ clients fetch to learn:

- latest and minimum supported versions
- notices
- feature flags
- (later) time-boxed limit adjustments and revocations

This lets us change behaviour without every user reinstalling. Hosting is static (GitHub Pages), so
everything in this folder is world-readable and contains **only signed, non-secret data**.

## Layout

```
policy/
  v1/
    index.html     # placeholder so /policy/v1/ resolves
    policy.json    # signed envelope for v1 clients (currently an unsigned placeholder)
  schema/v1/       # JSON Schemas: envelope + payload
  docs/            # field documentation, envelope format, hosting and mirrors
  examples/v1/     # illustrative unsigned payloads (not live policy)
  keys/            # published public keys (keys/<kid>.pub)
tools/policy/
  validate.py      # the validator used by CI (class based)
```

See [docs/schema-v1.md](docs/schema-v1.md) for the fields and compatibility rules and
[docs/envelope.md](docs/envelope.md) for the signed envelope format.

`/policy/v1/` is a stable contract: it stays alive for old clients even if a `/policy/v2/`
appears later. Never repurpose or remove a published version path.

## URLs

The client embeds this ordered list and tries each in turn:

| # | Role | URL |
|---|------|-----|
| 1 | Primary (GitHub Pages) | `https://coldsofttech.github.io/vethuq/policy/v1/policy.json` |
| 2 | Mirror (jsDelivr) | `https://cdn.jsdelivr.net/gh/coldsofttech/vethuq@main/policy/v1/policy.json` |
| 3 | Mirror (raw) | `https://raw.githubusercontent.com/coldsofttech/vethuq/main/policy/v1/policy.json` |

How the list is used and how to move hosts without a client release:
[docs/hosting-and-mirrors.md](docs/hosting-and-mirrors.md). Mirrors may be cached (jsDelivr in particular), so clients
rely on the signature and the policy's own validity fields, never on fetch freshness.

## Publishing flow

1. Draft the policy in the **private entitlements repo**.
2. Sign it with the **admin CLI** (the private key never leaves the admin environment).
3. Commit only the **signed output** to `policy/v1/policy.json`, via pull request.
4. The `policy-ci` check validates it; when the pull request is merged, the `policy-pages` workflow
   publishes the `policy/` folder. Verify the primary URL returns JSON.

Unsigned drafts are not authored here. `CODEOWNERS` asks for the owner's review on anything under
`policy/`.

## Checks

The `policy-ci` workflow runs when `policy/` or `tools/policy/` change, with no secrets (public keys only):

- envelope and payload schema (`policy/schema/v1/`)
- Ed25519 signature against the public key `policy/keys/<kid>.pub` (see [keys/README.md](keys/README.md))
- `sequence` strictly greater than the previous commit's `policy/v1/policy.json` (only when the file changed)
- notice and limit windows (`starts_at` before `ends_at`, real dates), URL, sha256 and version formats

Run locally from the repository root:

```bash
pip install jsonschema cryptography pytest
python -m pytest tools/policy/tests
python tools/policy/validate.py envelope policy/v1/policy.json --keys-dir policy/keys
```

While `policy/v1/policy.json` is the documented unsigned placeholder (`"_placeholder": true`), the check
passes with a warning. Once a signed policy replaces it, the placeholder is no longer accepted and the
file must verify like any other.

## Never commit

- Private keys or key material of any kind
- Licence issue logs
- Customer data (names, emails, licence identifiers tied to people)
- Unannounced promotions or anything not yet public
- Unsigned or hand-edited policy files

Everything here is world-readable and permanently in git history.
