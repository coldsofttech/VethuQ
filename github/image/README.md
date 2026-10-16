# Worker image

One public `linux/amd64` image repository, `ghcr.io/coldsofttech/vethuq-worker`, in variants, built
by `.github/workflows/github-image.yml` from the `Dockerfile` here. Each tag is `X.Y.Z-<variant>`
(`slim`, `office`, `web`, `developer`, `open-office`, `deep-scan`, `email`, `image`, `full`;
`X.Y.Z` alone is `full`). The variants are defined once, in
`packages/worker/src/vethuq_worker/variants.py`; the build, the workflow, the tests and the GitHub
tier all read that table. Every variant has every language. The tier asks for the lightest variant
that has the OCR phases a job needs (`slim`: quick; `deep-scan`: moderate and deep; `full` when
nothing lighter fits). The worker only reads rendered pages, so the file-type variants are for people
who run the image themselves.

No OCR models are in the image. The image carries `models.lock.json` (path, size and SHA-256 of every
model file); the runner fetches the models once (`vethuq-worker fetch-models`, the only step with a
network and no key or payload), caches them keyed by the lock's hash, and mounts them read-only at
`VETHUQ_MODELS`. The worker checks the models against the lock before each job (`models_missing`,
`models_unverified`). Layers are small: wheels and lists are bind-mounted rather than copied, the
virtual environment is stripped of tests, docs, caches and type stubs (`slim.py`), and layers are
zstd-compressed on push.

    docker run --rm --network none --user "$(id -u):$(id -g)" -e VETHUQ_MASTER_KEY \
      -v payload:/payload:ro -v out:/out ghcr.io/coldsofttech/vethuq-worker:X.Y.Z \
      run --job-id ID --payload /payload --out /out

The image is public and carries no secret, token or key; the master key arrives as an environment
variable at run time. It runs as an unprivileged user unless the caller passes `--user`.

## Building

Run the workflow (**Actions > github-image > Run workflow**, version `X.Y.Z`) or push a tag
`worker-image-vX.Y.Z`. Pull requests that touch this folder build and smoke-test without
publishing (the private checkouts need the secret, so they only run for branches in this repository).

1. Check out this repository, `VethuQ-premium` and `VethuQ-entitlements` side by side. The two
   private ones use the secret `PREMIUM_READ_TOKEN`: a fine-grained token with read-only
   **Contents** access to just those two repositories. Create it, then add it as a repository
   secret here.
2. Build the wheels (`addon-api`, `core`, `worker`, `entitlements`, and the add-ons named in the
   workflow's `PREMIUM_ADDONS`: every free add-on VethuQ depends on, so the image resolves them all, the image add-ons (PNG, JPG, TIFF, BMP, GIF, WebP, JPEG 2000, SVG, HEIC), the web file types (HTML, MHTML, XML, RSS, CSS, JavaScript, JSON, NDJSON, YAML: licensed; Word, Excel, PowerPoint, RTF and email: licensed, gated at runtime), Parquet (licensed, gated at runtime; brings PyArrow, the largest of the file-type dependencies), Telugu, Hindi, Urdu, French and Spanish (licensed: the wheels are gated at runtime like any licensed add-on) and the quick, moderate and deep OCR phases; moderate and deep use the server models, which `bake-models` fetches too, so a rotated read needs no network) and run `wheel_gate.py` over the add-ons: stable-ABI, compiled, no
   source, no key material. An `admin` wheel fails the build. Add a language bundle to the image by
   adding its directory name to `PREMIUM_ADDONS` and its wheel name to the `Dockerfile`; a test
   keeps the two lists equal.
3. Build the image, then smoke-test it with no network on the synthetic job in
   `github/protocol/v1/fixtures`.
4. Push `:X.Y.Z` and print a **compatibility row** (with the image digest) in the run summary.
   A person adds it to the add-on's table (`vethuq_addon_github/_compat.py` in `VethuQ-premium`)
   together with the `github-tier-vX.Y.Z` workflow tag; automation never rewrites rows.
5. The first time, make the package public (GitHub > Packages > vethuq-worker > settings), or the
   runners can't pull it.

Image versions are independent of VethuQ's, but each row pairs one image with one workflow tag,
one job protocol and a minimum client.

## What has and hasn't been verified

The workflow, Dockerfile and model baking are covered by tests that need no Docker
(`packages/worker/tests/test_image_files.py`, `packages/core/tests/test_worker_integration.py`).
The image itself is first built by the workflow; its smoke test is the real check.

## Supply chain

Every published variant is scanned (Trivy; the build stops on a CRITICAL finding that has a fix),
signed with cosign using the workflow's own identity (no key to keep), carries an SPDX SBOM as a
cosign attestation (and as the `worker-image-sbom` artifact for 90 days), and `full` has a build
provenance attestation. The compatibility table names images by digest, so the client never writes
one it does not list. To check an image:

```sh
cosign verify ghcr.io/coldsofttech/vethuq-worker@sha256:<digest> \
  --certificate-identity-regexp 'https://github.com/coldsofttech/VethuQ/.github/workflows/github-image.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
gh attestation verify oci://ghcr.io/coldsofttech/vethuq-worker@sha256:<digest> --repo coldsofttech/VethuQ
```
