# Job protocol v1

How the client and the worker exchange a job. Implemented by `packages/worker` (`vethuq-worker`).

- `manifest.schema.json` / `result.schema.json`: the two documents (copies of the schemas packaged
  in `vethuq_worker/schemas`; a test keeps them identical).
- `examples/`: a manifest and a result.
- `fixtures/`: a synthetic sealed payload and result under the public key in
  `packages/worker/tests/make_fixtures.py`, so any implementation can check it opens what another
  one sealed.

## Files

`payload.bin` (client to worker) and `result.bin` (worker to client) are both sealed files:

    "VQJ1" | salt (16) | chunk* ;  chunk = length (u32, big endian) | AES-256-GCM ciphertext

- Key: HKDF-SHA256 over the 256-bit master key, salted with the file's salt, with info
  `vethuq/v1/<purpose>/<job id>` (`purpose` is `payload` or `result`), so no two files share a key.
- Chunks hold up to 1 MiB of plaintext. The nonce is the chunk index (u64, big endian) and 4 zero
  bytes. The additional data is the job id, the index and a last-chunk flag, so chunks can't be
  reordered, cut off or moved to another job. Anything altered fails as `bad_payload`.

The payload's plaintext is a container: `VQC1`, an entry count, then entries (name, size, bytes).
Allowed names: `manifest.json` and `images/NNNN.png`.

## Manifest

`protocol` (1), `job_id`, `limits` (`max_pages`, `max_bytes`), optional `addon_settings` (the
licence tokens the add-ons read, by add-on id) and `pages`: each has a unique `key`, its image
`file`, its `language` id, `phase` and `size_factor`. Page text is never in the manifest.

## Result

`status` is `done`, `partial` (some pages failed) or `failed` (with an `error`). Each page has `ok`
and either the recognized `text`, `confidence`, `engine`, `language`, size and `lines`, or an
`error` (`language_unavailable`, `missing_image`, `ocr_failed`). `billable_seconds` is the time
spent reading, rounded up to a tenth of a second.

## Rules

- The caps are 200 pages and 200 MB per job; the worker enforces them whatever the manifest says
  (a manifest may only lower them). Breaking one fails the whole job (`too_many_pages`,
  `too_large`).
- Changes within v1 are additive; readers ignore fields they don't know. Another major version is
  refused (`unsupported_protocol`).
- The worker logs only counts and error types: never file names, page keys or OCR text. A job whose
  key and id are right always gets a sealed result, even a failed one; a wrong key can't be answered.
- Licences are checked by the add-ons themselves, from `addon_settings`; a page whose language or
  engine isn't licensed fails alone.

## Worker

    VETHUQ_MASTER_KEY=... vethuq-worker run --job-id ID --payload DIR --out DIR

reads `DIR/payload.bin` and writes `OUT/result.bin`. Exit code 0 when at least one page was read,
1 when the job failed, 2 for a usage problem (no or bad key). `VETHUQ_MODELS` points at the OCR models, which the
runner fetched once and cached (`fetch-models`); the worker verifies them against the image's
`models.lock.json` and fails with `models_missing` or `models_unverified` otherwise. The worker needs no network; run it without one where the runner allows.
