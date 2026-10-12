# Changelog

All notable changes to `vethuq-api`.

## [Unreleased]

### Added
- Sources and their files carry what they cost (`credits`), and files sort by it.
- Credits: `/api/credits/*` (summary for the status bar, wallets with lifetime totals, grants, usage by
  day, source or file, the daily series per wallet, the ledger, CSV/JSON exports, and redeeming a licence).
- Sources and indexing: `/api/sources` (list, add, remove, restore, delete for good, languages, files with
  filter, sort and paging from a short-lived scan, CSV/JSON export) and `/api/index/*` (state, refresh,
  start, pause, resume, stop, history, remote jobs, queued requests). A run goes to the background
  service's queue when one is working, else it runs on a thread inside the application. The Windows
  service is probed read-only (`sc query`) for the status bar, and `/api/service/<action>` controls it.
  `/api/dialog/file`, `/api/os/reveal`, and `/api/window/close` that holds back while a one-off run is going.
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
- Settings: the update check (with the skipped version and snooze shown read-only and clearable) in
  `general`, and a `system` section with log level and retention and the database integrity check.
- Settings: a `search` section (default engine, context, export format, the normalizers, each engine's
  own options), the data and backups folders (with moving the data), a section for the settings
  add-ons declare (`addons`), setting groups, and `GET /api/support-info` for a support report.
  `POST /api/dialog/folder` shows the host's folder picker where there is one.
