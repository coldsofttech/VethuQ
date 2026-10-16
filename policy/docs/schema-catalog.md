# Catalog schema v1

The catalog lists every **add-on** and **bundle** that exists, with descriptions, so that a person
can see what is available (not only what is installed) and ask for it. It is a second signed file
beside the policy, with its own counter:

- Payload: [`schema/v1/catalog.schema.json`](../schema/v1/catalog.schema.json)
- Envelope: the same as the policy's ([envelope.md](envelope.md)): `alg`, `kid`, `payload`, `sig`,
  signed with a policy key. A revoked key's catalog is refused like a revoked key's policy.
- Served at `/policy/v1/catalog.json`, with the same mirrors and ETag handling as `policy.json`.
- Example: [`examples/v1/catalog.example.json`](../examples/v1/catalog.payload.json)

The catalog says **what exists**. The policy's `addons` section ([schema-v1.md](schema-v1.md#add-ons-addons))
stays the operational part: the latest and minimum version of an add-on and its remote kill switch.
Versions are not repeated here.

## Compatibility

Additive within v1; clients ignore unknown fields and show an unknown `kind` or `status` as it is. All
text is plain text: clients must not render it as HTML. A client that cannot read a newer schema
major keeps the last catalog it accepted, as for the policy.

## Payload

Required: `schema_version` (1), `sequence` (>= 1, its own counter), `issued_at`, `kid` (= the
envelope `kid`), `addons`, `bundles`. Optional: `request_url`, the default place to ask for something.

### Add-on

| Field | Meaning |
|---|---|
| `id` | The add-on id (`semantic`, `docx`): lower case letters, digits and `-` |
| `label`, `summary` | Name (<= 80) and one line (<= 160) |
| `description` | Optional plain text, <= 2000 characters |
| `kind` | Optional: `file-type`, `language`, `search-engine`, `ocr`, `tier`, `backup`, or another word |
| `licence` | Optional: `free` or `licensed` |
| `bundles` | Optional: ids of the bundles that include it |
| `status` | Optional: `available` (default), `coming_soon`, `deprecated` |
| `min_client` | Optional: the oldest VethuQ it works with |
| `size_bytes`, `docs_url`, `request_url` | Optional |
| `translations` | Optional: `{ "es": { "label", "summary", "description" } }`; the entry's own text is the fallback |

### Bundle

`id`, `label`, `summary`, `description`, `status`, `docs_url`, `request_url`, `translations` as for an
add-on, and `addons`: the ids of the add-ons it includes (at least one).

## Rules the validator checks

Ids are unique; every add-on a bundle names exists; every bundle an add-on names exists; and the two
sides agree (a bundle lists an add-on only if that add-on lists the bundle); URLs are `https`; text has
no markup.

## What a client does with it

It fetches the catalog only when asked (`client.catalog.refresh()`), never when it starts, and never
when the update check is off. It keeps the last good catalog and ignores one that fails the signature,
comes from a revoked key, or has a lower sequence than the last one from that key. What it shows is the
catalog merged with what is installed here: installed, enabled, disabled, or not installed.
