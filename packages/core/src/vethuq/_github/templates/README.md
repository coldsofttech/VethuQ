# VethuQ runner

This repository was set up by VethuQ (`client.github.setup()`) to run OCR for you in your own
GitHub account. It holds one workflow, `.github/workflows/vethuq-ocr.yml`, and one secret,
`VETHUQ_MASTER_KEY`.

- VethuQ encrypts the pages that need OCR on your computer and uploads them here; a job decrypts
  them, reads them, and uploads the result, encrypted, for VethuQ to collect. Pages that have a
  text layer never leave your computer.
- Don't edit the workflow: `client.github.update()` rewrites it when a newer version is allowed.
- Don't share the master key. Losing it means results of past jobs can't be read.
- Anyone with write access to this repository can read the key's effects, so keep it private and
  keep access to yourself.

Set up by VethuQ. See https://github.com/coldsofttech/VethuQ.
