# Changelog

All notable changes to `vethuq-cli`.

## [Unreleased]

### Added (catalog)
- `vethuq catalog list|bundles|show|refresh`: every add-on and bundle that exists, with its description, licence and state on this computer, and where to ask for it. `list` takes `--missing`, `--bundle`, `--language`, `--json` and `--export`.

### Changed
- "Pack" is now "bundle" in the documentation.

### Documented
- The README describes `vethuq update`, the after-command notice, `vethuq policy notices`, the three update modes, `VETHUQ_UPDATE_CHECK` and what the policy fetch sends.

### Added
- `vethuq update` says whether a newer VethuQ exists and prints the exact upgrade steps for how it is installed (installer, pipx, virtual environment, externally-managed Python or pip), including add-ons that have a newer version. It changes nothing.
- A one-line notice after a command when a newer version is available, and the policy's active notices with their severity and link. It never asks anything, goes to stderr, and is not printed when the output is piped, with `--json`, or when the update check is off. `vethuq policy notices` lists the notices.
- `--export FILE` and `--format json|html` on the listing commands (sources and their files, the index queue,
  history and jobs, search engines and normalizers, file types, languages, tiers, credit history, OCR models,
  phases and engines, stats, add-ons), and `--format` on `search --export`. The HTML has filters.
- The `vethuq` command line on the public API: sources, index (with live status), search, the settings
  hierarchy, languages, tiers, credits, metrics, OCR models, database, logs, stats, updates, policy and
  add-ons; commands installed add-ons describe with `Addon.cli()`.
