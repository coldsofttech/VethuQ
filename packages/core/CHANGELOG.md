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
- **Languages** (`client.languages.list_all()`): a `languages` table seeded with English, and a
  `source_languages` table linking sources to the languages they are read in. An unknown language
  raises `LanguageUnavailableError`.
- **Settings** (`client.settings`): source retention for removed sources (7 days by default), log
  level and retention (`LogLevel`, 15 days by default), and update-check settings
  (`UpdateCheckMode`, snooze and skip). Changes to the log settings apply at once.
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
  `vethuq-addon-api~=0.1`.

### Notes
- The production policy signing keys are not built in yet, so `client.policy.refresh()` makes no
  request and reports `SKIPPED`.
- Only the `pip` distribution is supported by the update check. The desktop app's installer
  version is added when that app exists.
- Everything other than the names documented in the README is internal and may change without
  notice.
