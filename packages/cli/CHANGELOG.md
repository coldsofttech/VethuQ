# Changelog

All notable changes to `vethuq-cli`.

## [Unreleased]

### Added
- `--export FILE` and `--format json|html` on the listing commands (sources and their files, the index queue,
  history and jobs, search engines and normalizers, file types, languages, tiers, credit history, OCR models,
  phases and engines, stats, add-ons), and `--format` on `search --export`. The HTML has filters.
- The `vethuq` command line on the public API: sources, index (with live status), search, the settings
  hierarchy, languages, tiers, credits, metrics, OCR models, database, logs, stats, updates, policy and
  add-ons; commands installed add-ons describe with `Addon.cli()`.
