# Changelog

All notable changes to the `VethuQ` package are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions come from git tags named
`vethuq-vX.Y.Z` (through hatch-vcs), not from this file; until the first tag, the version is `0.1.0`.

## [Unreleased]

### Added
- Package `VethuQ` (import name `vethuq`), versioned from git tags, exposing `APP_NAME`,
  `APP_TAGLINE`, `APP_VERSION` and `__version__`.
- `vethuq.VethuQ` client, the entry point to every feature below. It connects to the database on
  first use and can be used as a context manager.
- **Sources** (`client.sources`, types in `vethuq.sources`): `create`, `get`, `list` (filter by
  status, type and language; sort by field and order; include removed), `list_files`,
  `set_languages`, `remove`, `purge` and `purge_expired`. Results are `Source`, `SourceFile` and
  `PurgeResult`, with `to_dict()` and `to_json()`. `SourceType`, `SourceStatus`, `SourceSortBy` and
  `SortOrder` enums.
- **Document index** (internal `documents` and `document_index` tables): which files a source
  holds and where each is in indexing, by absolute path. `sources.list_files(id, detailed=True)`
  adds a `FileIndex` to each file (`FileStatus`: pending, processing, indexed, error, modified,
  removed, unsupported; sha256; the original of a duplicate) and also lists indexed files that
  have gone from disk until the source is purged. `status=` filters. Only PDF is supported for
  now. Reading never changes anything.
- **Source progress**: a source's `status` is now overall (`SourceStatus`: pending, in_progress,
  completed, error, removed), with `files_processed`, `files_total` and a `progress` text.
- Sources can't overlap: `create` raises `SourceOverlapError` for a path inside an active source or
  one that contains it. Purging a source deletes the record of its files.
- **Languages** (`client.languages`): languages come from language add-ons (add-on API 0.2.0,
  `Addon.languages()`); English is the free `vethuq-addon-english`, the system default, installed
  with VethuQ. `list_all`, `list_enabled`, `get`, `default`, `enable` and `disable`. A language is
  used when it is available (add-on installed and, if licensed, licensed) and enabled; disabling
  one saves the credits it costs, and at least one must stay in use (`LastLanguageError`). A
  disabled or unavailable language is refused for sources (`LanguageUnavailableError`). The
  `source_languages` table links sources to the languages they are read in.
- **Language settings** (`client.settings.languages`): the languages a source with none of its own
  is read in; English unless changed.
- **Settings** (`client.settings`): source retention for removed sources (7 days by default), log
  level and retention (`LogLevel`, 15 days by default), and update-check settings
  (`UpdateCheckMode`, snooze and skip). Changes to the log settings apply at once.
- **Indexing** (`client.index`, types in `vethuq.index`): `run(target=None, workers=None)`
  indexes every source, one source, or one file in a source, and returns an `IndexRun`; `get` and
  `history` (filter by target, status and time; sort; page). Native text first, then OCR: native
  pages need none, mixed pages read only their images, scanned pages are read whole. Files with
  the same content share their pages; a document read in a new language is merged. Failed files are
  retried and picked up again by later runs, password-protected files are `UNSUPPORTED`, and a run
  whose process died is failed at the next run. `IndexRunStatus`, `IndexRunSortBy`,
  `IndexAlreadyRunningError` and `IndexRunNotFoundError`. Purging a source deletes its runs.
- **Index settings** (`client.settings.index`): workers (`auto` or 0 to 8), retry attempts (3) and
  the stability check (1 second).
- **File types** (`client.file_types`), from add-ons (add-on API 0.3.0); PDF is `vethuq-addon-pdf`
  (pypdfium2). `list_files(detailed=True)` now also shows each file's pages, confidence, languages
  and file type.
- **OCR** (`client.ocr`): `engines`, `phases` and `models` (list, download, redownload, clear,
  clean). The engine is `vethuq-addon-paddle` (PaddleOCR, models in `<data root>/models`) and the
  phase `vethuq-addon-ocr-quick` (mobile models, upright pages). These three add-ons are free and
  installed with VethuQ.
- **Credits** (`client.credits`, types in `vethuq.credits`): the local wallet (500 a day, a 2,000
  starter, 2% free grace, no rollover), priced by page size from the signed policy's rate card with
  built-in defaults; `balance`, `next_reset`, `estimate`, `history` (filter, sort, page), `redeem` and
  `redeem_licence` (licence credit grants, once each). Pages are paid for as they are read and a
  file that fails is refunded; native pages, duplicates and unchanged files are free. When credits
  run out the run ends as `IndexRunStatus.WAITING_CREDITS` and continues after the reset. A policy
  change applies from the next UTC day. Errors `CreditsError`, `InvalidGrantError`,
  `CreditsExhaustedError`; `IndexRun` gains `pages_processed`, `ocr_pages` and `credits_charged`.
- **Statistics** (`client.stats`, types in `vethuq.stats`): `overview` (group by source, language,
  file type, engine, page source, confidence band or day; filter; sort; page), `source`, `failures`
  and `low_confidence_pages`, from daily totals that outlive files and purged sources.
  **Confidence bands** (`settings.confidence`; high from 90%, medium 80%, low 70%, below that
  unreliable); `list_files(detailed=True)` shows `band` and `low_confidence_pages` and filters by
  `min_confidence` and `band`.
- **Metrics sharing** (`client.metrics`, off by default): `status`, `opt_in`, `opt_out`, `preview`,
  `send` and `delete_data`. A content-free batch of the daily totals goes to the policy's collector
  at the end of an index run, at most once a day; sharing earns +10% daily credits. The batch
  schema and the collector (a Cloudflare Worker with D1) are in `metrics/`.
- **Processing tiers** (`client.tiers`, types in `vethuq.tiers`): where pages that need OCR are
  read. `local` (the default, on this computer), `github` (the GitHub add-on) and `hybrid`;
  `list`, `get`, `current`, `use` and `reset`. Tiers come from add-ons
  (`Addon.processing_tiers()`, add-on API 0.4.0) as an `OcrExecutor`; local OCR now runs through
  one. `index.run(tier=, wait=, timeout=)`, `IndexRun.tier` and the run status `WAITING_REMOTE`
  (remote tiers can't run yet). `TierError` and `TierUnavailableError`.
- **Pages are saved one at a time**: a page is saved (and its credits charged and counted) the
  moment it is read, so a file that stops part way (no credits, a failure, a crash) keeps its
  pages and the next attempt, in the same run or a later one, carries on after the last saved
  page without paying for them again. A page whose OCR is still to come is saved `waiting`.
- **Remote jobs** (`client.index.jobs()`, `client.index.collect()`, `RemoteJob`,
  `RemoteJobStatus`): a tier that works in batches gets the images of pages that need OCR, paid
  for when staged, in jobs bounded by `settings.tiers`; the run ends `WAITING_REMOTE` unless
  `wait=True`. Finished jobs are imported (files become indexed once all their pages arrive);
  failed, expired or empty results are refunded and their pages sent again later. Internal
  tables `remote_jobs` and `remote_job_pages`; `pdf_pages` gains a `status`.
- **Tier settings** (`client.settings.tiers`): hybrid size rule and phases, wait timeout and remote
  job limits.
- **Wallets by tier**: `credits.wallets()`, `credits.balance(wallet)`, `history(wallet=)`; the
  GitHub wallet (20 a day for a private runner repository, 200 for a public one), with promotions
  and the metrics bonus. `CreditBalance` and `CreditEntry` carry their wallet.
- **GitHub runner** (`client.github`, types in `vethuq.github`): `setup`, `status`, `update`,
  `remove`, `runner` and `versions`. Creates (or adopts) a private repository you own, writes the
  caller workflow, and sets the master key as a secret (sealed with the repository's public key;
  kept in `<data root>/github/master.key`). Only runner versions in the compatibility table are
  written; the policy feature `github_tier` is the kill switch. Errors `GitHubError`,
  `GitHubAuthError`, `GitHubSetupError`, `GitHubNotSetUpError`, `GitHubUnavailableError`. The
  reusable workflow `.github/workflows/github-ocr.yml` and the layout are in `github/`; this
  replaces the separate `VethuQ-github-tier` repository. The worker image is not built yet.
- Internal tables `credit_grants`, `credit_ledger`, `usage_daily` and `usage_failures`.
- Internal tables `pdf_pages`, `pdf_pages_quick`, `document_languages` and `index_runs`.
- **Logs** (`client.logs`, types in `vethuq.logs`): one class per log (`DatabaseLog`, `IndexLog`,
  `UiLog`, `CliLog`, `PolicyLog`) with `file`, `tail`, `read` (filter by level, day and text; sort by
  time), `follow`, `export` and `logger`. Daily files with retention and safe rotation;
  `LogEntry`, `LogFile`, `LogComponent` and `LogLevel`.
- **Version** (`client.version`): `VersionDetails` with the VethuQ, Python, platform and database
  schema versions. The lists of installed file types, search engines, OCR engines, OCR languages,
  add-ons and bundles are placeholders for now.
- **Database schema version**: a `schema_version` table. A database written by a newer VethuQ is
  refused with `SchemaVersionError`; an older one is migrated step by step.
- **Policy** (`client.policy`, types in `vethuq.policy`): fetches the signed `policy.json`, verifies
  its Ed25519 signature, protects against rollback, supports key revocation, caches it in
  `<data root>/policy/`, and falls back to a built-in baseline. It never raises and fetches nothing
  unless asked. `VETHUQ_POLICY_URLS` overrides the URLs.
- **Updates** (`client.updates`, types in `vethuq.updates`): `status`, `check` and `feature`, with
  `UpdateResult`, `FeatureAccess`, snooze, skip-version and the `VETHUQ_UPDATE_CHECK` override.
  The signed policy is the only source of update information.
- **Paths** (`vethuq.Paths`): read-only locations of the data folder, database, backups, run, logs
  and policy folders. The data root comes from `VETHUQ_HOME`, then the saved `db.json`, then the
  platform default.
- **Errors** (`vethuq.errors`): a `VethuQError` root with `message`, `hint` and `exit_code`.

  | Exit code | Errors |
  |---|---|
  | 1 | `VethuQError`, `StartupError` |
  | 10 to 16 | `InvalidConfigError`, `DataFolderNotWritableError`, `CorruptDatabaseError`, `OcrModelMissingError`, `SchemaVersionError`, `StaleLockError`, `LanguageUnavailableError` |
  | 20 to 24 | `SourceError`, `SourcePathError`, `SourceAlreadyExistsError`, `SourceNotFoundError`, `SourceNotRemovedError` |
  | 30, 31 | `SettingsError`, `InvalidSettingValueError` |
  | 40 to 42 | `LogError`, `LogNotFoundError`, `InvalidLogRequestError` |
  | 50 to 52 | `IndexingError`, `IndexAlreadyRunningError`, `IndexRunNotFoundError` |
  | 60 to 62 | `CreditsError`, `InvalidGrantError`, `CreditsExhaustedError` |
  | 80, 81 | `TierError`, `TierUnavailableError` |
  | 70 to 74 | `GitHubError`, `GitHubAuthError`, `GitHubSetupError`, `GitHubNotSetUpError`, `GitHubUnavailableError` |

- **Database integrity check** (`client.db`, types in `vethuq.db`): `integrity_check(quick=False)` and
  `integrity_status()`, with `IntegrityCheckResult` and `IntegrityCheckMode`. The check runs by itself
  when the database is opened (`AUTO` once per interval, `ENABLE`, or `DISABLE`) and its result is saved
  and logged. A failed check, or a file SQLite can't read, raises `CorruptDatabaseError`; the check
  itself works on a database VethuQ refuses to open. Settings in `client.settings.database`.
- Opening the database permanently deletes the sources removed longer ago than the retention.
- **Add-ons** (`client.addons`, types in `vethuq.addons`): finds installed add-ons by their
  `vethuq.addons` entry point, lists them as `AddonInfo` with an `AddonStatus`, and gives each
  namespaced settings (`client.addons.settings(id)`). `from vethuq.addons.<id> import ...` reaches an
  installed add-on's public classes. Two best-effort hooks: after the database opens and before a
  schema migration. VethuQ deploys no add-on and works unchanged without them.
- Policy: `Policy.addons` (`AddonPolicy`: `enabled`, `latest`, `minimum_supported`, `min_client`,
  `message`) and `Policy.revoked_licence_ids`.
- Dependencies: `platformdirs~=4.0`, `sqlalchemy~=2.0`, `cryptography~=50.0`, `packaging~=26.0`,
  `vethuq-addon-api~=0.1`, `vethuq-addon-english~=0.1`.

### Notes
- The production policy signing keys are not built in yet, so `client.policy.refresh()` makes no
  request and reports `SKIPPED`.
- Only the `pip` distribution is supported by the update check. The desktop app's installer
  version is added when that app exists.
- Everything other than the names documented in the README is internal and may change without
  notice.
