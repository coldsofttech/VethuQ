# Policy schema v1

The schema is the contract between this repo, the core client and the admin tool.

- Envelope: [`schema/v1/envelope.schema.json`](../schema/v1/envelope.schema.json) (see [envelope.md](envelope.md))
- Payload: [`schema/v1/policy.schema.json`](../schema/v1/policy.schema.json) (JSON Schema draft 2020-12)
- Examples: [`examples/v1/`](../examples/v1/)

## Compatibility rules

1. **Additive only within a major.** Within v1 we may add optional fields, new enum values for
   fields documented as extensible, and new top-level sections. We never remove, rename or
   change the meaning or type of an existing field.
2. **Unknown fields are ignored.** Clients MUST ignore fields (and `features` entries) they do not
   understand. The schema leaves `additionalProperties` open for this reason.
3. **Breaking changes go to a new major**, served from `/v2/`. `/v1/` stays available for old clients.
4. Clients treat a missing optional section as "nothing to apply".

## Payload fields

Required: `schema_version`, `sequence`, `issued_at`, `kid`, `versions`.

### Metadata

| Field | Type | Description |
|---|---|---|
| `schema_version` | integer, const `1` | Schema major. |
| `sequence` | integer >= 1 | Monotonic. Clients reject a sequence that is not greater than the floor for the signing key (rollback protection; per-key rules in [envelope.md](envelope.md#rollback-protection-and-forged-sequences)). |
| `issued_at` | date-time (UTC) | When the policy was signed. |
| `kid` | string | Signing key id. Must equal the envelope `kid`; clients reject a mismatch. |

### `versions` (required)

Keys `desktop` and `pip`, each a distribution object:

| Field | Type | Description |
|---|---|---|
| `latest` | semver | Newest released version. |
| `minimum_supported` | semver | Clients below this must update. |
| `release_notes_url` | https URL, optional | Release notes for `latest`. |
| `downloads` | array, optional | Per-platform entries (normally desktop only). |

Download entry (all required): `platform` (e.g. `windows-x64`, `macos-arm64`, `linux-x64`),
`url` (https), `size` (bytes), `sha256` (lowercase hex). Clients MUST verify `sha256`.

### `compatibility` (optional)

`addon_api.min` / `addon_api.max`: inclusive semver range of the add-on API supported by `latest`.

### `notices` (optional)

Array of `{ id, message, severity, link?, starts_at?, ends_at? }`.
`severity` is `info`, `warning` or `critical`. `id` is stable so a dismissed notice stays dismissed.
A notice is shown only inside its optional time window (open-ended when a bound is omitted).
`message` is plain text, max 500 characters; clients must not render it as HTML.

### `features` (optional)

Object keyed by flag name (`^[a-z][a-z0-9_]*$`), each `{ enabled, min_client? }`.
`min_client` limits the flag to clients at or above that version. `enabled: false` is also the
remote kill switch. An absent flag means the client's built-in default applies.
Example: `"github_tier": { "enabled": false, "min_client": "1.0.0" }`.

### `limits` (optional)

Generic time-boxed limit adjustments. Credit promotions use the `promotions` section below instead. **Structure only; policies issued in the initial v1
rollout leave it empty or omit it.** Item (all required except `min_client`):
`id`, `kind` (`limit_adjustment` | `promotion`), `starts_at`, `ends_at`, `min_client?`,
`adjustments` (object of name to number/boolean/string). Applies only while now is inside
`[starts_at, ends_at]`. Which adjustment names exist is defined by the client when it implements them;
unknown names are ignored.

## Credits sections (additive, optional)

These sections deliver the credit rates, limits and promotions by signed policy so they can change
without a client release (#198, #199). All are optional and additive within v1; a client that does
not understand a field ignores it. **The package keeps a baseline** for every value: it is used
until a policy is available, and for any value the policy leaves out.

Credit amounts are non-negative numbers with **at most 3 decimal places** (clients convert to
integer millicredits).

### Terms: add-ons and packs

An **add-on** is one individual element (Word, Excel, PowerPoint, Email, Lexical, Semantic, ...).
A **pack** (Office, Web, Telugu, the text pack, ...) is a bundle of add-ons licensed together.
Everything in this schema that names an add-on (`wallets.addons.<id>`, `promotions[].applies_to.addons`,
the `addon:<id>` uplift wallet key) uses the **add-on** id, such as `semantic`, never a pack name.
Packs are not part of the schema yet (see "Not defined yet").

### When changes take effect

- Rates are the **same for every client version** unless a section carries an explicit `applies_to`.
- A new rate card or limit change takes effect at the **next UTC day boundary** after the client
  first sees it. The day in progress keeps the rates it started with.
- Optional top-level `effective_from` (a UTC date `YYYY-MM-DD`) delays that: sections `rate_card`,
  `wallets`, `caps`, `grace_percent`, `grace_mode`, `metrics` and `ocr` take effect at the **later**
  of `effective_from` and that next boundary. It never makes a change apply earlier.
- Promotions are not delayed by `effective_from`; they follow their own whole-day windows.
- Reservation estimates and settlement within one day use the same rate card.

### `applies_to` (optional, on the payload and on sections)

`applies_to.client` is an inclusive client-version range, `{ "min"?: semver, "max"?: semver }`.
Absent means all versions. A section's own `applies_to` replaces the payload-level one for that
section. `min` must not exceed `max`. On `promotions`, `applies_to.tiers` and `applies_to.addons`
filter who gets the promotion; they are ignored elsewhere.

### `rate_card`

`version` (integer >= 1, required) is stamped on every ledger row and increases with every change.
All other members are optional and fall back to the baseline.

| Member | Meaning |
|---|---|
| `page_size` | `tolerance_percent`, `step`, `minimum`, `per_page_max`: credits = page area / A4 area, rounded up to `step` after the tolerance, at least `minimum`; pages above `per_page_max` are refused |
| `pixels` | `reference_megapixels`, `step`, `minimum`: credits for images = processed pixels / reference |
| `phases` | `quick`, `moderate`, `high`: credits per A4 page added by each OCR phase |
| `rotated_factor` | Multiplier per rotated angle pass (a pricing discount) |
| `language_pass` | Credits per page per extra language |
| `semantic` | Credits per page for semantic embedding (from its own sub-wallet) |
| `device_multiplier` | `cpu`, `gpu`: multiplier by the device actually used |
| `model_multiplier` | `fast`, `advanced`: multiplier by OCR model profile |

### `wallets`

| Member | Meaning |
|---|---|
| `local` | `daily`, `starter` (one-off per device) |
| `github` | `daily_private`, `daily_public`, `starter`. The client picks the daily value from the visibility of the runner repo it checks before each job |
| `addons` | Sub-wallets keyed by add-on id: `local_daily`, `github_daily`, `starter`. Usable only for that add-on's work |

### `promotions`

Array of `{ id, name, start_date, end_date, uplift, applies_to?, min_client?, message? }`.

- `start_date` / `end_date` are UTC dates (inclusive), so a window is always whole UTC days.
  `start_date` must not be after `end_date`; impossible dates are rejected; `id` must be unique.
- `uplift` maps a wallet key (`local`, `github`, `addon:<id>`) to **exactly one** of
  `{ "absolute": credits }` or `{ "percent": n }`. It is added to that wallet's daily allowance on
  each day inside the window and ends with the window.
- Non-stacking: the highest uplift per wallet applies, capped by `caps`.
- `min_client` and `applies_to.client` both limit the client versions; both must be satisfied.

### `caps`

`promotion_uplift_percent`, `one_off_max`, `one_off_expiry_days`, `device_daily_ceiling`,
`metrics_bonus_percent` (default 15). Validation rejects a promotion percent above
`promotion_uplift_percent` and a `metrics.bonus_percent` above the metrics cap.

### `grace_percent`, `grace_mode`

Grace is a percentage (default 2) of a wallet's daily allowance, used only after all other credits
are exhausted. `grace_mode` is `free` (default) or `borrow` (the used grace is deducted from the
next day). An unknown mode is ignored and the default used.

### `metrics`

`enabled`, `endpoint` (https), `max_batch_bytes`, `bonus_percent` (default 10, capped by
`caps.metrics_bonus_percent`). The bonus applies to the daily credits of the local and GitHub
wallets only while sharing is on and the last send was within 7 days. (The field is
`metrics.bonus_percent`; earlier discussion called it `metrics_bonus_percent`.)

### `ocr`

`profiles` overrides the model profile per phase (`quick`, `moderate`, `high` to `fast` or
`advanced`), for example to force `fast` everywhere as a kill switch for the advanced models.
Absent phases use the client's default.

### Not defined yet

Pack definitions (which add-ons a pack contains) and scoped one-off amounts (#221) may become policy-tunable; they are not part of
the schema yet and will arrive as a further additive section.

### Key revocation (`revoked_key_ids`)

Optional array (max 32, unique) of signing key ids the client must stop trusting. Without it, a
compromised key stays trusted until the user installs a client or runtime release that drops it.
Additive within v1: **clients that do not understand the field ignore it** and keep trusting the key
until they update, so a release that drops the key is still part of the response.

Rules (client behaviour; the schema only carries the list):

1. **Who may revoke.** A revocation is honoured only if the envelope `kid` is in the client's
   embedded **policy-standby** key set. A policy signed by an active policy key is still valid, but
   its `revoked_key_ids` is ignored. Reason: if a compromised active key could revoke the standby,
   the attacker would hold the only trusted key and the owner would have no in-band recovery.
2. **What may be revoked.** Any key id of any purpose (policy, licence, bundle) **except** the
   signing key itself and the policy-standby keys. A standby key can only be replaced by a client
   release. Entries naming those are ignored. The validator rejects a policy that lists its own `kid`.
3. **Immediate.** Revocation is a security action and applies as soon as the policy is accepted. The
   next-UTC-day rule and `effective_from` do not apply to it.
4. **Permanent.** The client persists the revoked set across restarts and updates. It only grows: a
   later policy that omits an id does not restore it. A key id derives from the key material, so a
   revoked key never comes back.
5. **Scope of the refusal.** Anything signed by a revoked key id is refused: policies, licences and
   bundle manifests. Licences signed by a revoked licence key stop verifying, so affected licences
   must be re-issued with the replacement key.
6. **Fails closed for trust, open for work.** If the revoked key was the only trusted signer left,
   the client keeps the last accepted policy and baseline values and shows a notice, and local work
   is never blocked.
7. **Sequence.** A revoking policy is an ordinary policy, but it is signed by a standby key, whose
   floor is that key's own last sequence. A forged very high sequence from a compromised key
   therefore cannot block it, and once the revocation is accepted the forged number stops
   counting ([envelope.md](envelope.md#rollback-protection-and-forged-sequences), #266).

Example: `examples/v1/with-key-revocation.payload.json`.

### `revocations` (reserved)

Licence ids to revoke. **Reserved and MUST be empty in v1** (the schema enforces `maxItems: 0`).
Clients ignore it until a later additive change defines its use.
