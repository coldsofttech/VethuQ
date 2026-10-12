# Changelog

All notable changes to `vethuq-api`.

## [Unreleased]

### Added
- The Flask application for the user interface: `create_app()`, a one-time start-up token that is
  exchanged for a session cookie, Host and Origin checks, a strict Content-Security-Policy, the
  `/api/health`, `/api/about`, `/api/platform` and `/api/window/*` endpoints, and serving of the built
  React interface.
- Settings endpoints, starting with the `indexing` section: index workers, retries, stability wait and
  stale-lock handling, OCR depth and GPU use. `/api/brand` and `/api/catalog` for the app's name and
  colours and for what is installed.
- Settings sections `general` (default languages, usage metrics), `sources` (removed-source retention),
  `tiers` (default processing tier, hybrid OCR phases and size rule, remote job limits, wait timeout) and
  `results` (confidence bands), with list, multi-choice and three-number (`bands`) setting types.
