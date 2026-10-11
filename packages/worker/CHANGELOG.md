# Changelog

All notable changes to the `vethuq-worker` package are documented here. Versions come from git
tags named `vethuq-worker-vX.Y.Z` (through hatch-vcs), not from this file.

## [Unreleased]

### Added
- Job protocol v1: manifest and result schemas, a chunked AES-256-GCM sealed file format (per-job
  HKDF keys; chunks bound to the job, their order and the end of the file) and a payload container
  of the manifest and PNG page images.
- Client side: `JobBuilder` (adds `OcrRequest`s under the 200 pages / 200 MB caps, seals the job),
  `open_result` and `to_ocr_results`.
- Worker: `run_job` and the `vethuq-worker run --job-id ID --payload DIR --out DIR` command (key in
  `VETHUQ_MASTER_KEY`). It reads the pages with VethuQ's local OCR over the installed add-ons,
  applies the add-on settings (licences) from the manifest, enforces the caps, fails single pages
  without failing the job, logs nothing from the documents, and always seals a result.
- `vethuq-worker bake-models --models DIR`: downloads the OCR models for every installed language
  and phase and proves each engine loads, so the image needs no network at run time.
- The image: `github/image/Dockerfile` and `.github/workflows/github-image.yml` (builds the wheels
  from the three repositories, gates the add-on wheels, builds, smoke-tests with no network, pushes
  to GHCR and prints the compatibility row).
