# Worker image

One public `linux/amd64` image, `ghcr.io/coldsofttech/vethuq-worker`, built by
`.github/workflows/github-image.yml` from the `Dockerfile` here. It holds the worker
(`packages/worker`), VethuQ, the add-ons' wheels (compiled; gated at runtime by the licence) and
the OCR models (`vethuq-worker bake-models`, run during the build so jobs need no network).

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
   workflow's `PREMIUM_ADDONS`: every free add-on VethuQ depends on, so the image resolves them all) and run `wheel_gate.py` over the add-ons: stable-ABI, compiled, no
   source, no key material. An `admin` wheel fails the build. Add a language pack to the image by
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
