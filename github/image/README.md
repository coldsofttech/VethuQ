# Worker image

Planned (phase 4): a `Dockerfile` for one public `linux/amd64` image
(`ghcr.io/coldsofttech/vethuq-worker`) holding the worker (`packages/worker`, extra `run`), core,
entitlements, the add-on wheels (gated at runtime by the licence) and the baked-in OCR models
(`VETHUQ_MODELS`). Its entrypoint is `vethuq-worker run --job-id ID --payload DIR --out DIR`.
Published to GHCR as a public package; tags and digests are recorded in
`packages/core/src/vethuq/_github/compatibility.json`.
