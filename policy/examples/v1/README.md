# Examples (not served as policy)

Unsigned, illustrative payloads valid against `schema/v1/policy.schema.json`. They are **not** the live
policy; the live signed envelope is `/v1/policy.json`. All URLs, hashes and the key id are fictional.

| File | Shows |
|---|---|
| `minimal.payload.json` | Smallest valid payload |
| `with-notice.payload.json` | A notice with a time window and link |
| `feature-disabled.payload.json` | A feature flag disabled (kill switch) |
| `with-promotion-window.payload.json` | Downloads, add-on API range and a time-boxed promotion |
| `with-rate-card.payload.json` | The credits sections: rate card, wallets (GitHub private/public daily), a promotion, caps, grace, metrics, OCR profiles and `effective_from` |
| `rate-card-scoped.payload.json` | A rate card limited to clients >= 1.2.0 with an advanced-model multiplier, and an OCR profile override forcing `fast` |
| `with-key-revocation.payload.json` | A policy signed by a standby key that revokes a compromised policy key id and a licence key id, with a critical notice and a raised `minimum_supported` |
| `with-addons.payload.json` | Per add-on policy (`addons.backup`) and `revoked_licence_ids` |
| `envelope.example.json` | Envelope wrapping the minimal payload (placeholder signature, does not verify) |
