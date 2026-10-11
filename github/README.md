# GitHub runner

Run OCR in **your own GitHub account**. `GitHub(client).setup()` (the free `vethuq-addon-github` add-on) makes (or uses) a repository you
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
| `packages/worker` | The job protocol (`vethuq-worker`): sealed files, the client's `JobBuilder`, and the worker the image runs |
| `VethuQ-premium/packages/github` | The add-on: `setup()`, the caller workflow it writes (`_compat.py`), the table of versions it may set up, and the executor that sends and collects jobs |
| `github/protocol/v1/` | The job protocol (manifest and result), shared by client and worker tests |
| `github/image/` | The worker image: `Dockerfile` and how it is built and published |

There is **no template repository**. GitHub copies a template whole, which would put this monorepo
in every user's account, so the client writes the one file instead.

## Rules

- The caller has one trigger, `workflow_dispatch`, two plain inputs (job id and asset reference),
  minimal permissions and a concurrency group. The pin and the image are on single, parseable lines
  that `GitHub(client).update()` rewrites. The run is named `vethuq <job id>`, which is how the
  add-on finds it.
- Only combinations in the add-on's compatibility table are ever written to a runner repository: the image
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
3. Add a row to the add-on's compatibility table (`vethuq_addon_github/_compat.py`; never edit or
   remove one; mark a bad one `withdrawn`), set its status to `released`, and release the add-on.
4. Users move with `GitHub(client).update()`.

## Job life cycle

1. `index.run(tier="github")` renders the pages that need OCR; the add-on seals them into one
   payload (`vethuq-worker`'s `JobBuilder`) and creates a pre-release `job-<id>` in the runner
   repository with the payload as its asset.
2. It dispatches the caller workflow (`job_id`, `asset`); the run is titled `vethuq <job id>`.
3. The reusable workflow downloads the asset, runs the image with no network and uploads the sealed
   result as the artifact `vethuq-result-<id>` (one day of retention).
4. `index.collect()` (or the next run) polls the run, downloads the artifact (the token is never
   sent to the storage host it redirects to), opens the result and imports the pages.
5. The add-on deletes the release, its tag and the artifact. A job that fails, is cancelled or
   never starts is cleaned the same way, and its credits are given back.

## Status

The add-on, the protocol, the worker and the image build are in place. The one row in the table is
`provisional` until the first image is published and a row with its digest is added.
