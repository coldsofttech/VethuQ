# GitHub runner

Run OCR in **your own GitHub account**. `client.github.setup()` makes (or uses) a repository you
own, puts VethuQ's thin caller workflow in it and gives it a master key as a secret. VethuQ then
encrypts the pages that need OCR, uploads them to that repository, and a GitHub Actions job runs
the worker image on them; the result comes back encrypted. This folder and
`.github/workflows/github-ocr.yml` are the public side of that.

```mermaid
sequenceDiagram
    participant C as VethuQ client (your machine)
    participant R as Your runner repo
    participant W as github-ocr.yml + worker image (this repo)
    C->>R: setup(): caller workflow + VETHUQ_MASTER_KEY secret
    C->>C: Extract the pages that need OCR, encrypt them
    C->>R: Upload the encrypted payload as a release asset, dispatch the caller (job id, asset)
    R->>W: Call the pinned reusable workflow
    W->>W: Pull the image, decrypt with the master key, run OCR, enforce the manifest's limits
    W->>R: Upload the encrypted result as an artifact (1-day retention)
    C->>R: Poll, download, decrypt, import; delete the asset and artifact
```

## What is here

| Path | Purpose |
|---|---|
| `.github/workflows/github-ocr.yml` | The reusable workflow (`workflow_call`). Callers pin it by tag: `coldsofttech/VethuQ/.github/workflows/github-ocr.yml@github-tier-vX.Y.Z` |
| `packages/core/src/vethuq/_github/templates/vethuq-ocr.yml` | The caller workflow `setup()` writes into the user's repository. It ships inside the package, so it always matches the client |
| `packages/core/src/vethuq/_github/compatibility.json` | Which workflow tags, images and job protocol versions this VethuQ may set up |
| `github/protocol/v1/` | The job protocol (manifest and result), shared by client and worker tests |
| `github/image/` | The worker image (planned) |

There is **no template repository**. GitHub copies a template whole, which would put this monorepo
in every user's account, so the client writes the one file instead.

## Rules

- The caller has one trigger, `workflow_dispatch`, two plain inputs (job id and asset reference),
  minimal permissions and a concurrency group. The pin and the image are on single, parseable lines
  that `client.github.update()` rewrites.
- Only combinations in `compatibility.json` are ever written to a runner repository: the image
  holds the master key's effects, so VethuQ never runs one it did not list. The reusable workflow
  checks the image name again.
- Everything is encrypted (chunked AES-GCM, per-job keys from the master key). Only the job id and
  asset reference are plain. The worker makes no outbound calls; its container has no network.
- Native-text pages never leave your computer.
- Never commit keys, tokens, real documents or OCR text.

## Token

A fine-grained personal access token, limited to the runner repository once it exists:
*Contents*, *Actions*, *Secrets* and *Workflows* (read and write). To let `setup()` create the
repository, or `remove(delete_repo=True)` delete it, add *Administration*; otherwise create an
empty repository yourself and call `setup(..., create=False, adopt=True)`. The token is used for
the call and never stored. Pass `token=` or set `VETHUQ_GITHUB_TOKEN`.

## Releasing a runner version

1. Build and publish the worker image from the published wheels; record its digest.
2. Tag the repository `github-tier-vX.Y.Z` (the tag the caller pins).
3. Add a row to `compatibility.json` (never edit or remove one; mark a bad one `withdrawn`), set
   its status to `released`, and release VethuQ.
4. Users move with `client.github.update()`.

## Status

The client side (`client.github`), the caller, the reusable workflow and the compatibility table are
in place. The worker (`vethuq-worker`), its image and the job protocol schemas are not built yet,
so the one row in `compatibility.json` is `provisional`.
