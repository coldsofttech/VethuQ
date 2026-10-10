# VethuQ

VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

See the [changelog](CHANGELOG.md) for what each release adds.

## Installation

```bash
pip install VethuQ
```

## Application identity

`vethuq` exposes the application's name, tagline and version:

| Name | Value | Description |
|---|---|---|
| `vethuq.APP_NAME` | `"VethuQ"` | The application name |
| `vethuq.APP_TAGLINE` | `"Document intelligence and evidence infrastructure."` | The short tagline |
| `vethuq.APP_VERSION` | e.g. `"0.1.0"` | The installed version |
| `vethuq.__version__` | same as `APP_VERSION` | Standard Python alias |

```python
import vethuq

print(vethuq.APP_NAME)  # VethuQ
print(vethuq.APP_TAGLINE)  # Document intelligence and evidence infrastructure.
print(vethuq.APP_VERSION)  # 0.1.0

from vethuq import APP_NAME, APP_VERSION

print(f"{APP_NAME} {APP_VERSION}")
```

### Versioning

The version is not edited by hand. It comes from git tags named `vethuq-vX.Y.Z` (for example `vethuq-v0.1.0`), through hatch-vcs.

- On a tagged release, the version is exactly the tag, for example `0.1.0`.
- Commits after a tag get a development version, such as `0.1.1.dev3+g<hash>`.
- If the package isn't installed, for example when running from a source checkout, `APP_VERSION` is `0.1.0`.

## Errors

Every error VethuQ raises on purpose is a subclass of `vethuq.errors.VethuQError`. Catch that for any of them, `StartupError` for the failures that stop VethuQ from starting, `SourceError` for the source errors, `SettingsError` for the settings errors, `LogError` for the log errors, or a specific subclass for one failure.

| Error | Exit code | Category | Raised when |
|---|---|---|---|
| `VethuQError` | 1 | Base class | Root of all the errors below |
| `StartupError` | 1 | Base class | Root of the startup failures below |
| `InvalidConfigError` | 10 | Startup | The saved settings file or the `VETHUQ_HOME` setting can't be used |
| `DataFolderNotWritableError` | 11 | Startup | VethuQ can't create or write to its data folder |
| `SchemaVersionError` | 14 | Startup | The database's schema is newer than this build supports |
| `StaleLockError` | 15 | Startup | A lock file exists but its process is no longer running |
| `CorruptDatabaseError` | 12 | Run time | The database file is damaged or isn't a VethuQ database, or it failed its integrity check when opened |
| `OcrModelMissingError` | 13 | Run time | The OCR engine or its model files aren't available |
| `LanguageUnavailableError` | 16 | Run time | A language was asked for that isn't installed, available, enabled or known |
| `LastLanguageError` | 17 | Run time | The last language in use can't be disabled |
| `SourceError` | 20 | Sources | Root of the source errors below |
| `SourcePathError` | 21 | Sources | A source path doesn't exist, or is neither a file nor a folder |
| `SourceAlreadyExistsError` | 22 | Sources | The path is already registered as an active source |
| `SourceNotFoundError` | 23 | Sources | No source matches the id or path (or it is removed, when only active ones are searched) |
| `SourceNotRemovedError` | 24 | Sources | The source is still active, so it can't be purged |
| `SourceOverlapError` | 25 | Sources | The path lies inside an active source, or contains one |
| `LogError` | 40 | Logs | Root of the log errors below |
| `LogNotFoundError` | 41 | Logs | There is no log for that component and day |
| `InvalidLogRequestError` | 42 | Logs | A log request had a bad `lines`, `day`, `level`, `order` or component |
| `SettingsError` | 30 | Settings | Root of the settings errors below |
| `InvalidSettingValueError` | 31 | Settings | A setting was given a value it doesn't accept |

Every error has three attributes:

- `message`: what is wrong, in plain language.
- `hint`: what to do about it (`None` if there is no suggestion).
- `exit_code`: a distinct non-zero code, so a front end can exit with it.

`str(error)` joins the message and the hint.

```python
import sys

import vethuq

try:
    ...  # start VethuQ
except vethuq.errors.StartupError as error:  # config, data folder, schema, lock
    print(f"Could not start: {error}")
    sys.exit(error.exit_code)
except vethuq.errors.VethuQError as error:  # any other VethuQ error
    print(error)
    sys.exit(error.exit_code)
```

## Paths

`Paths` reports where VethuQ keeps its data. Import it with `from vethuq import Paths` (it is also available as `vethuq.paths.Paths`). It is read-only: it returns paths and creates nothing on disk.

```
<data root>/
    db/             vethuq.db
    db/backups/     database backups (unless relocated)
    run/            runtime coordination files
    logs/           log files
    policy/         the cached policy and its state
```

| Member | Returns |
|---|---|
| `Paths.DB_NAME` | `"vethuq.db"`, the database file name |
| `Paths.CONFIG_FILENAME` | `"db.json"`, the name of the per-user settings file |
| `Paths.ENV_VAR` | `"VETHUQ_HOME"`, the environment variable that relocates the data |
| `Paths.data_root()` | The folder all VethuQ data lives under |
| `Paths.db_dir()` | The folder holding the database (`<data root>/db`) |
| `Paths.db_path()` | The database file (`<data root>/db/vethuq.db`) |
| `Paths.backups_dir()` | The folder backups are kept in |
| `Paths.run_dir()` | The folder for runtime coordination files |
| `Paths.logs_dir()` | The folder for log files |
| `Paths.policy_dir()` | The folder for the cached policy and its state |
| `Paths.config_file()` | The per-user `db.json`, which stores a relocated data root |

All the methods return `pathlib.Path` objects.

```python
from vethuq import Paths

print(Paths.db_path())  # e.g. /home/you/.local/share/VethuQ/db/vethuq.db
print(Paths.logs_dir())  # e.g. /home/you/.local/share/VethuQ/logs
print(Paths.DB_NAME)  # vethuq.db
```

### Where the data root comes from

The data root is chosen in this order:

1. The `VETHUQ_HOME` environment variable, if set.
2. The location saved in the per-user `db.json`.
3. The platform default (for example `%APPDATA%\VethuQ` on Windows, `~/.local/share/VethuQ` on Linux).

The backups folder is `<data root>/db/backups` unless a different one is saved in `db.json`.

## Client

`vethuq.VethuQ` is the entry point. It works with one VethuQ database and gives access to the features through attributes such as `client.sources`.

```python
import vethuq

client = vethuq.VethuQ()  # the default database: Paths.db_path()
client = vethuq.VethuQ(db_path="/data/vethuq.db")  # or another database file
```

`client.sources`, `client.languages`, `client.settings`, `client.logs`, `client.policy`, `client.updates`, `client.db` and `client.version` are the features available so far. The database is created the first time it is used. Use the client as a context manager, or call `close()`, to release it when you are done:

```python
with vethuq.VethuQ() as client:
    client.sources.create("~/docs")
```

## Sources

A source is a file or folder you register for OCR and indexing. Folders are read recursively. `Source`, `SourceFile`, `PurgeResult` and the enums used with sources are in `vethuq.sources`.

```python
import vethuq

client = vethuq.VethuQ()

source = client.sources.create("~/docs", languages=["en"])  # register it
source = client.sources.get(source.id)  # look one up
sources = client.sources.list()  # list them
files = client.sources.list_files(source.id)  # the files that belong to it
source = client.sources.set_languages(source.id, ["en"])  # change its languages
source = client.sources.remove(source.id)  # remove it
result = client.sources.purge(source.id)  # delete it for good
```

A source is identified by its **id** (an `int`) or its **path** (a `str` or `pathlib.Path`). `~` and relative paths are resolved, so the same folder written two ways is the same source. A string of digits such as `"2024"` is a path, never an id.

### The `Source` details

| Field | Description |
|---|---|
| `path` | The absolute path (required when you create a `Source`) |
| `languages` | The languages it is read in, for example `["en"]`; `None` means the global language setting applies |
| `id` | The source's id |
| `source_type` | A `SourceType`: `FILE` or `FOLDER` |
| `status` | The overall `SourceStatus`, worked out from its files: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `ERROR` or `REMOVED` (see [Source progress](#source-progress)) |
| `files_total` | How many files count towards its progress (not unsupported or removed ones) |
| `files_processed` | How many of them are processed (indexed, or failed) |
| `progress` | The same in words, for example `"3 of 10 files processed"` (a property, not part of `to_dict()`) |
| `added_at` | When it was registered (UTC, ISO 8601) |
| `last_scanned_at` | When it was last scanned, or `None` |
| `is_active` | `True` unless it has been removed |
| `removed_at` | When it was removed, or `None` |

`id`, `source_type`, `status`, `files_total`, `files_processed`, `added_at`, `last_scanned_at`, `is_active` and `removed_at` are set by VethuQ, so they are `None` on a `Source` you describe yourself.

Every method that returns a source returns a `Source`, and it can be turned into a dict or JSON:

```python
source.to_dict()
source.to_json(indent=2)
```
```json
{
  "id": 1,
  "path": "/home/you/docs",
  "type": "folder",
  "status": "pending",
  "files_processed": 0,
  "files_total": 0,
  "added_at": "2026-10-10T12:23:42.600727+00:00",
  "last_scanned_at": null,
  "languages": ["en"]
}
```
`languages` appears only when the source has some.

### Enums

The fixed choices are enums, available from `vethuq.sources` (`vethuq.sources.SourceStatus`, and so on). They are strings too: `SourceStatus.PENDING == "pending"`, they print and serialise as their value, and anywhere a method takes one you may pass the plain string instead.

| Enum | Members |
|---|---|
| `SourceType` | `FILE`, `FOLDER` |
| `SourceStatus` | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `ERROR`, `REMOVED` |
| `FileStatus` | `PENDING`, `PROCESSING`, `INDEXED`, `ERROR`, `MODIFIED`, `REMOVED`, `UNSUPPORTED` |
| `SortOrder` | `ASC`, `DESC` |
| `SourceSortBy` | `ID`, `PATH`, `STATUS`, `SOURCE_TYPE`, `ADDED_AT`, `LAST_SCANNED_AT` |

### Creating a source

`client.sources.create()` registers a source and returns its details.

```python
# from a path
source = client.sources.create("~/docs")

# with the languages it is read in
source = client.sources.create("~/docs", languages=["en"])

# or describe it with a Source object
described = vethuq.sources.Source("~/docs", languages=["en"])
source = client.sources.create(described)

print(source.id, source.path, source.source_type, source.status)
# 1 /home/you/docs folder pending
```

- `languages` is a list of language ids. Give it on the call or on the `Source`, not both.
- Re-creating a source that was removed brings it back, reset to `pending`.
- The `Source` you pass in is left untouched; `create` returns a new, filled-in one. A `Source` that was already created can't be passed again.

### Getting one source

```python
client.sources.get(1)
client.sources.get("~/docs")
client.sources.get(1, include_removed=True)  # also finds a removed source
```
Raises `SourceNotFoundError` if nothing matches. A removed source is found only with `include_removed=True`.

### Listing sources

```python
client.sources.list()  # active sources, by id
client.sources.list(include_removed=True)  # and the removed ones
client.sources.list(
    status=vethuq.sources.SourceStatus.PENDING,
    source_type=vethuq.sources.SourceType.FOLDER,
    language="en",
    sort_by=vethuq.sources.SourceSortBy.PATH,
    order=vethuq.sources.SortOrder.DESC,
)
```

| Argument | Description |
|---|---|
| `include_removed` | Include removed sources. Default `False` |
| `status` | Only sources with this `SourceStatus`. `REMOVED` shows removed sources whatever `include_removed` says |
| `source_type` | Only files or only folders |
| `language` | Only sources read in this language id; an unknown one raises `LanguageUnavailableError` |
| `sort_by` | A `SourceSortBy`. Default `ID` |
| `order` | A `SortOrder`. Default `ASC` |

The filters combine. Ties in the sort are broken by id. A value that isn't one of the enums raises `ValueError` listing the options.

### Listing the files of a source

`client.sources.list_files()` lists the files that belong to an active source, as they are on disk right now.

```python
for file in client.sources.list_files(1):
    print(file.relative_path, file.size_bytes)
# a.pdf 20480
# reports/2026.pdf 51200
```

- A **folder** source gives every file under it, however deep, sorted by path relative to the folder (ignoring case). Links to folders are not followed, and folders that can't be read are skipped.
- A **file** source gives that same file.
- A folder with no files gives an empty list.

Each item is a `SourceFile`:

| Field | Description |
|---|---|
| `path` | The absolute path |
| `relative_path` | The path relative to the source folder, with `/` separators (just the name for a file source) |
| `name` | The file name |
| `size_bytes` | The size in bytes |
| `modified_at` | When it was last modified (UTC, ISO 8601) |

It has `to_dict()` and `to_json(indent=None)` like the other results. It raises `SourceNotFoundError` if no active source matches, and `SourcePathError` if the source's folder or file is no longer on disk.

#### Where each file is in indexing

`detailed=True` adds an `index` (a `FileIndex`) to every file:

```python
for file in client.sources.list_files(1, detailed=True):
    print(file.relative_path, file.index.status)
# a.pdf FileStatus.INDEXED
# b.pdf FileStatus.PENDING
# notes.txt FileStatus.UNSUPPORTED
# old.pdf FileStatus.REMOVED

errors = client.sources.list_files(1, detailed=True, status="error")  # only the failures
```

| `FileStatus` | Meaning |
|---|---|
| `PENDING` | Not processed yet (including a file VethuQ hasn't seen) |
| `PROCESSING` | Being processed now |
| `INDEXED` | Processed |
| `ERROR` | Processing failed; see `error` |
| `MODIFIED` | Changed on disk since it was indexed. It will be processed again |
| `REMOVED` | Indexed once and no longer on disk. It stays listed (with `on_disk` false) until the source is purged |
| `UNSUPPORTED` | A kind of file VethuQ can't read yet. Only PDF is supported for now |

A `FileIndex` has `status`, `on_disk`, `error`, `sha256` (known once the file has been read), `indexed_at`, `retry_count` and `duplicate_of` (for a file with the same content as an earlier one: the path of that original), plus `to_dict()` and `to_json()`. `status` (a `FileStatus` or its string) keeps only the files in that state and needs `detailed=True`. Reading never changes anything; the index is written as files are processed. The documents behind it are internal.

### Source progress

A source's `status` follows its files, and `files_processed` of `files_total` tells how far it is:

| `status` | When |
|---|---|
| `PENDING` | Nothing is processed or processing yet |
| `IN_PROGRESS` | Some files are done and others still wait, or one is being processed |
| `COMPLETED` | Every file is processed |
| `ERROR` | Every file is processed, but some failed |
| `REMOVED` | The source was removed |

```python
source = client.sources.get(1)
print(source.status, source.progress)  # SourceStatus.IN_PROGRESS 3 of 10 files processed
```

Unsupported and removed files don't count towards the total.

### Changing the languages

```python
client.sources.set_languages(1, ["en"])  # read in English
client.sources.set_languages(1, None)  # back to the global language setting ([] works too)
```
It returns the updated `Source` and affects files indexed from then on. It works on active sources only (a removed one raises `SourceNotFoundError`), and an unknown language raises `LanguageUnavailableError` and changes nothing.

### Removing and purging

Removing a source is reversible; purging is not.

```python
removed = client.sources.remove(1)  # kept, but marked REMOVED and no longer active
client.sources.create("~/docs")  # registering it again brings it back, with the files it knew

result = client.sources.purge(1)  # permanently deleted
print(result.to_json())  # {"id": 1, "path": "/home/you/docs", "type": "folder"}
```

- `remove` works on active sources and returns the removed `Source`. Removing one that is already removed raises `SourceNotFoundError`.
- `purge` works only on removed sources and returns a `PurgeResult` (`id`, `path`, `source_type`, with `to_dict()` and `to_json()`). An active source raises `SourceNotRemovedError`; an unknown one raises `SourceNotFoundError`. A purged source's language choices and the record of its files go with it.
- `purge_expired()` purges every source that has been removed for longer than the retention, and returns the list of `PurgeResult`s. The retention is 7 days unless you change it in the [settings](#settings). Pass `retention_minutes=` to use another value for one call.

```python
client.sources.purge_expired()  # uses the setting (7 days by default)
client.sources.purge_expired(retention_minutes=60)  # removed more than an hour ago
```

### Languages of a source

VethuQ keeps a list of the languages it can read (see [Languages](#languages) for how to list them). English (`en`) is there from the start, and others are added as they become available. A source stores the languages it is read in, and a source with none uses the global language setting.

- Language ids are case-insensitive and may be repeated; `["EN", "en"]` is stored as `["en"]`.
- Languages are always returned in VethuQ's own language order, not the order you gave them.
- A language VethuQ doesn't know raises `vethuq.errors.LanguageUnavailableError`, and nothing is changed. The hint lists the available languages, and every unknown id is reported at once:

```python
try:
    client.sources.create("~/docs", languages=["en", "xx"])
except vethuq.errors.LanguageUnavailableError as error:
    print(error)  # Unknown language 'xx'. Available languages: en.
```

A plain string such as `"en,te"` isn't accepted; pass a list.

### Source errors

| Raised | When |
|---|---|
| `SourcePathError` | The path doesn't exist (or, for `list_files`, is no longer on disk), or is neither a file nor a folder |
| `SourceAlreadyExistsError` | The path is already an active source, or the `Source` given was already created |
| `SourceNotFoundError` | No source matches the id or path |
| `SourceNotRemovedError` | `purge` was called on a source that is still active |
| `SourceOverlapError` | `create` was given a path inside an active source, or one that contains an active source. Sources can't overlap, so a file never belongs to two |
| `LanguageUnavailableError` | A language isn't one VethuQ knows, its add-on is missing or unavailable, or it is disabled |

All of them are `VethuQError`s; the first five are also `SourceError`s.

## Languages

`client.languages` is about the languages VethuQ can read documents in. Languages come from **language add-ons**; English (`vethuq-addon-english`, free) is installed with VethuQ, so it is always there and enabled. Other languages arrive as add-ons you install (and, if licensed, hold a licence for).

A language is **used** only when it is both:

- **available**: its add-on is installed and usable now (for a licensed one, its licence is valid), and
- **enabled**: you haven't switched it off. Every language starts enabled; switch one off to stop spending credits on it.

```python
import vethuq

client = vethuq.VethuQ()

for language in client.languages.list_all():
    print(language.id, language.label, language.enabled)
# en English True
# te Telugu True

client.languages.list_enabled()  # only the languages that are used
client.languages.get("te")  # one Language, or None if VethuQ doesn't know it
client.languages.default()  # the system default language: English
client.languages.disable("te")  # stop using Telugu (and the credits it costs)
client.languages.enable("te")  # use it again
```

`list_all()` gives the system default first, then the others by id. It also lists a language a source still refers to whose add-on has since been removed (`installed` is false).

| Field of a `Language` | Description |
|---|---|
| `id` | The language id used everywhere (creating a source, the settings, `get`), for example `"en"` |
| `label` | Its name, for example `"English"` |
| `native_label` | Its name in its own script (`"తెలుగు"`), or empty |
| `script` | The writing system, for example `"latin"` |
| `default` | `True` for the system default language |
| `installed` | Its add-on is installed |
| `available` | Installed and usable now |
| `enabled` | Not switched off by you |
| `reason` | Why it isn't available, when it isn't |
| `usable` | A property: `available` and `enabled` |

A `Language` has `to_dict()` and `to_json(indent=None)`.

### The default language

`default()` returns English, the system default. It is the fallback when nothing else is usable, and it describes the system, not your choices: it still returns English if you have disabled it.

### Disabling a language

`disable(id)` switches a language off so nothing uses it, whatever the language costs per page. `enable(id)` switches it back on (it must be available). Both return the updated `Language`.

- At least one language must stay in use: disabling the last usable one raises `LastLanguageError`.
- A disabled language can't be chosen anywhere: `sources.create`, `sources.set_languages` and `settings.languages.set_languages` raise `LanguageUnavailableError` ("disabled", with a hint to enable it). A source that already uses it keeps its choice, and `sources.list(language=...)` still finds it.
- Disabling a language also takes it out of the default languages setting.
- If nothing usable is left because a licence lapsed or an add-on was removed, VethuQ falls back to the system default (English) and logs a warning, rather than failing.
- An unknown id raises `LanguageUnavailableError`.

Any usable language id can be passed as `languages=[...]` when you create a source; any other raises `LanguageUnavailableError` saying why (unknown, add-on missing or unavailable, or disabled).

## Settings

`client.settings` reads and changes VethuQ's settings, grouped by feature. A setting you haven't changed has its default.

### Source settings

`client.settings.sources` holds the settings for sources.

| Method | Description |
|---|---|
| `get_removed_retention_minutes()` | How long a removed source is kept before `purge_expired()` deletes it. 10080 minutes (7 days) by default |
| `set_removed_retention_minutes(minutes)` | Change it. `0` means removed sources are purged at the next `purge_expired()` |
| `reset_removed_retention_minutes()` | Back to the default |

```python
client.settings.sources.get_removed_retention_minutes()  # 10080
client.settings.sources.set_removed_retention_minutes(24 * 60)  # keep for one day
client.settings.sources.reset_removed_retention_minutes()
```

A value that isn't a whole number of 0 or more raises `vethuq.errors.InvalidSettingValueError`, and the setting is left as it was. Settings are saved in the database, so every client using that database sees the same values.

### Language settings

The languages a source with none of its own is read in.

```python
client.settings.languages.get_languages()  # ["en"] (the system default) unless changed
client.settings.languages.set_languages(["en", "te"])  # returns the list saved
client.settings.languages.reset_languages()  # back to the system default
```

`set_languages` takes a list of usable language ids (available and enabled) and raises `LanguageUnavailableError` for any other, or `InvalidSettingValueError` for an empty list. A saved language that stops being usable is left out when read; if none are left, the system default applies. Disabling a language also removes it from this setting.

### Database settings

`client.settings.database` holds the settings for the database (see [Database](#database)). They are read when the database is opened, so a change applies the next time a client opens it.

| Method | Description |
|---|---|
| `get_integrity_check()` | When the integrity check runs by itself, as an `IntegrityCheckMode`. `AUTO` by default |
| `set_integrity_check(mode)` | `AUTO` checks when the database is opened, at most once per interval; `ENABLE` checks every time it is opened; `DISABLE` never checks by itself (`client.db.integrity_check()` still works). The strings `"auto"`, `"enable"` and `"disable"` work too |
| `reset_integrity_check()` | Back to `AUTO` |
| `get_integrity_check_interval_minutes()` | Minutes between automatic checks in `AUTO` mode. 1440 (one day) by default |
| `set_integrity_check_interval_minutes(minutes)` | Check at most once per `minutes`; at least 1 |
| `reset_integrity_check_interval_minutes()` | Back to one day |

```python
client.settings.database.set_integrity_check(vethuq.db.IntegrityCheckMode.ENABLE)
client.settings.database.set_integrity_check_interval_minutes(60)
```

A mode that isn't an `IntegrityCheckMode`, or an interval that isn't a whole number of at least 1, raises `InvalidSettingValueError` and changes nothing.

### Update settings

`client.settings.updates` holds the settings for the [update check](#updates).

| Method | Description |
|---|---|
| `get_check()` | What the check does, as an `UpdateCheckMode`. `ON` by default |
| `set_check(mode)` | `ON` checks and offers to update, `NOTIFY_ONLY` checks and only tells you, `OFF` never checks (`"notify-only"` and the other strings work too) |
| `reset_check()` | Back to `ON` |
| `disabled_by_environment()` | Whether `VETHUQ_UPDATE_CHECK` switches the check off |
| `snooze(days=1)` | Hide the notice for `days` days ("remind me later") |
| `get_snoozed_until()` | When the snooze ends (UTC), or `None` |
| `clear_snooze()` | Show the notice again |
| `skip_version(version)` | Stop announcing this version only; a newer one is announced again |
| `get_skipped_version()` | The version being skipped, or `None` |
| `clear_skip()` | Announce every version again |

Set the environment variable **`VETHUQ_UPDATE_CHECK`** to `off` (also `0`, `false`, `no`, `disable` or `disabled`) to switch the check off whatever the setting says, for CI and locked-down machines. It wins over the setting.

A mode that isn't an `UpdateCheckMode`, a snooze that isn't a number of days above 0, or an empty version raises `InvalidSettingValueError` and changes nothing.

### Log settings

`client.settings.logs` holds the settings for the logs (see [Logs](#logs)).

| Method | Description |
|---|---|
| `get_level()` | How much the logs record, as a `LogLevel`. `INFO` by default |
| `set_level(level)` | Record entries at or above this `LogLevel` (`"warning"` works too) |
| `reset_level()` | Back to `INFO` |
| `get_retention_days()` | How many days of daily log files are kept. 15 by default |
| `set_retention_days(days)` | Keep `days` days of files; at least 1 |
| `reset_retention_days()` | Back to 15 |

```python
client.settings.logs.set_level(vethuq.logs.LogLevel.WARNING)
client.settings.logs.set_retention_days(30)
```

A level that isn't a `LogLevel`, or a retention that isn't a whole number of at least 1, raises `InvalidSettingValueError` and changes nothing. A change applies at once to logs that are already being written.

## Logs

VethuQ keeps a log for each of its parts. They are plain text files in the `logs` folder of the data folder (`Paths.logs_dir()`), one file per day. Old days are kept for the retention set in the [log settings](#log-settings) (15 days by default).

`client.logs` has one attribute per log, each its own class with the same methods:

| Attribute | Class | `LogComponent` | File | What it logs |
|---|---|---|---|---|
| `client.logs.database` | `DatabaseLog` | `DATABASE` | `database.log` | The database: opening it, schema upgrades, sources and settings changes |
| `client.logs.index` | `IndexLog` | `INDEX` | `index.log` | Indexing: the background index runs and every OCR worker thread |
| `client.logs.ui` | `UiLog` | `UI` | `ui.log` | The desktop app |
| `client.logs.cli` | `CliLog` | `CLI` | `cli.log` | The command line: each command that ran and how it finished |
| `client.logs.policy` | `PolicyLog` | `POLICY` | `policy.log` | The policy and update checks: fetching and verifying the signed policy |

All of them extend `Log`. `client.logs.get("cli")` finds one by name or by `LogComponent`. The classes, `LogEntry`, `LogFile` and the enums `LogComponent` and `LogLevel` are all in `vethuq.logs`.

### Listing the logs

```python
for file in client.logs.list():  # today's file of every log
    print(file.component, file.exists, file.size_bytes)

file = client.logs.database.file()  # one log's file for today
file = client.logs.database.file("2026-10-09")  # ... or for a past day (a date works too)
print(file.path)
```

A `LogFile` has `component`, `path`, `exists`, `size_bytes` and `modified_at` (UTC; both `None` if the file isn't there) and `days`, every day that has a log, oldest first. Looking never creates a file or folder.

### Reading a log

```python
log = client.logs.cli

log.tail()  # the last 40 entries, oldest first
log.tail(100, level=vethuq.logs.LogLevel.ERROR)  # the last 100 errors
log.read(day="2026-10-09")  # every entry of a past day
log.read(contains="schema", order=vethuq.logs.SortOrder.DESC)  # newest first, text match
```

| Argument | Applies to | Description |
|---|---|---|
| `lines` | `tail` | How many of the most recent entries. Default 40 |
| `day` | `tail`, `read` | A `date` or `"YYYY-MM-DD"`. Today by default |
| `level` | `tail`, `read` | Entries at or above this `LogLevel` |
| `contains` | `tail`, `read` | Entries whose message contains this text, ignoring case. The level, thread and logger are not searched |
| `order` | `tail`, `read` | A `SortOrder` by time. `ASC` (oldest first) by default |

The filters combine, and are applied before `tail` counts its `lines`.

Each entry is a `LogEntry`:

| Field | Description |
|---|---|
| `timestamp` | When it was logged (local time) |
| `level` | A `LogLevel` |
| `thread` | The thread that logged it |
| `logger` | The logger's name, for example `vethuq.database` |
| `message` | The message, with its traceback if it has one |
| `raw` | The entry exactly as it is in the file |

An entry that isn't in the usual format keeps only `message` and `raw`, and always passes a level filter. `to_dict()` and `to_json(indent=None)` give everything except `raw`.

### Following a log

```python
for entry in client.logs.index.follow(level="warning"):
    print(entry.message)  # runs until you stop it, like `tail -f`
```

`follow()` starts from the end of today's file, so it shows only what is written from then on. It takes `level` and `contains`, and a `stop` function that ends it when it returns `True`. It carries on across the daily rollover and waits for a log that doesn't exist yet.

### Exporting a log

```python
count = client.logs.cli.export("errors.txt", level="error")
client.logs.cli.export("last.txt", lines=100, order="desc")
```

This writes the selected entries as plain text, one entry per line (a traceback stays with its entry), overwriting the file, and returns how many were written. It takes `lines` (otherwise every entry), `day`, `level`, `contains` and `order`.

### Writing to a log

The database log is written by VethuQ itself. The other parts write through the standard `logging` module:

```python
logger = client.logs.cli.logger()
logger.info("ran: sources list")
logger.error("failed: %s", "boom")
```

`logger()` returns the `logging.Logger` for that log (`vethuq.cli`), set up to write to the log file at the level and retention from the settings. Log paths, ids and counts, not document text or what someone searched for: log files outlive the access controls on the documents.

Loggers belong to the process, not to a client. If two clients use different databases in one process, each log is written next to the database that was set up last.

### Log errors

| Raised | When |
|---|---|
| `LogNotFoundError` | There is no log for that component and day |
| `InvalidLogRequestError` | `lines` isn't a whole number of at least 1, or `day`, `level`, `order` or a component name can't be used |

Both are `LogError`s and `VethuQError`s.

## Policy

The policy is a small signed file that tells VethuQ the latest and minimum versions, notices and feature flags, without anyone reinstalling. VethuQ fetches it, checks its Ed25519 signature against keys built into VethuQ, and keeps the last good copy. Until one is accepted, a built-in baseline applies (no notices, no features, every version `0.0.0`).

```python
client = vethuq.VethuQ()

result = client.policy.current()  # the cached policy or the baseline; no network
result = client.policy.refresh()  # check for a newer one (about once a day)
result = client.policy.refresh(force=True)  # ignore the once-a-day limit
thread = client.policy.refresh_in_background()  # the same, on a daemon thread

policy = result.policy
policy.versions["pip"].latest  # "2.0.0" (a DistributionVersions)
policy.active_notices()  # notices whose time window includes now
policy.features["some_feature"].enabled
```

The types are in `vethuq.policy`: `Policy`, `DistributionVersions`, `Notice`, `Feature`, `AddonPolicy`, `PolicyResult` and the enums `PolicySource` and `PolicyStatus`.

A `PolicyResult` has:

| Field | Meaning |
|---|---|
| `policy` | The `Policy` to use. Sections VethuQ doesn't use yet stay available in `policy.raw` / `policy.to_dict()` |
| `source` | `FETCHED` (accepted by this call), `CACHE` (the last accepted policy, checked again from disk) or `BASELINE` |
| `status` | `CURRENT`, `UPDATED`, `UNCHANGED`, `SKIPPED`, `OFFLINE`, `REJECTED` or `UPDATE_REQUIRED` |
| `detail` | Why a fetch failed or was refused, for logs; the update message when `update_required` |
| `update_required` | The latest policy needs a newer VethuQ than this one |

A `Policy` also carries `addons` (per add-on `AddonPolicy`: `enabled`, `latest`, `minimum_supported`, `min_client`, `message`) and `revoked_licence_ids`, which licensed add-ons read.

It also has `to_dict()` and `to_json()`.

### Guarantees

- **No network unless asked.** Nothing is fetched on `import vethuq`, when a client is created, or by `current()`. Only `refresh()` and `refresh_in_background()` use the network.
- **Never raises, never blocks.** `current()` and `refresh()` always return a `PolicyResult`: offline, every URL failing, a bad signature, a damaged cache or a read-only data folder just keep the last good policy (or the baseline).
- **Trust comes from the signature, not the host.** A response is accepted only if it verifies against a built-in key, so a wrong or hostile mirror can make a fetch fail but cannot change the policy.
- **No rollback.** A policy with a lower `sequence` than one already accepted is refused. A standby key can revoke a compromised signing key.
- **A newer schema.** A correctly signed policy that needs a newer VethuQ is not applied; the last compatible policy stays and `update_required` is set (`"Update VethuQ to receive new policy."`).

Until the production signing keys are built in, `refresh()` makes no request and returns `SKIPPED`.

### Where it comes from

The policy is published from the `policy/` folder of the VethuQ repository on GitHub Pages. VethuQ tries these in order and uses the first that verifies:

1. `https://coldsofttech.github.io/vethuq/policy/v1/policy.json`
2. `https://cdn.jsdelivr.net/gh/coldsofttech/vethuq@main/policy/v1/policy.json`
3. `https://raw.githubusercontent.com/coldsofttech/vethuq/main/policy/v1/policy.json`

Each request has a 2.5 s timeout, a 5 s total limit and a 256 KiB size cap, and only `https` is used. An ETag lets an unchanged policy answer "nothing newer". After a failed check VethuQ waits an hour before trying again.

To use a staging file or a company mirror, set **`VETHUQ_POLICY_URLS`** to a comma- or space-separated list of `https` URLs. It replaces the list above for that process; entries that aren't well-formed `https` URLs are dropped, and if none are left the defaults are used.

### What is stored

In the `policy` folder of the data folder (`Paths.policy_dir()`), as two small files:

| File | Contents |
|---|---|
| `policy.json` | The last accepted policy, exactly as served |
| `state.json` | The highest accepted sequence per key, revoked key ids, the ETag, and the last check and failure times |

They are plain files, not database rows, on purpose: the policy and the update check keep working even when the database can't be opened (for instance when it is newer than this VethuQ supports), and resetting the database does not erase the rollback protection. The folder is disposable: a missing or damaged file means "never fetched". What happens is written to the `policy` log (`client.logs.policy`).

### Privacy

Fetching the policy exposes your IP address to its host. The request identifies itself only as `VethuQ-policy/1`; **your VethuQ version is not sent** (the comparison happens on your machine). Nothing else is sent, and GitHub Pages gives no access logs to us. Turn the update check off and nothing is fetched on its behalf (see [Update settings](#update-settings)).

## Updates

`client.updates` tells you when a newer VethuQ exists and which features need one. The signed policy is the **only** source: there is no fallback to PyPI or GitHub Releases, so an update is announced only when it is published in the policy.

```python
result = client.updates.check()  # refresh the policy (about once a day) and report on it
result = client.updates.status()  # use the saved policy only; no network
if result.notify:
    print(result.message)  # "VethuQ 2.0.0 is available (you have 1.5.0)."

access = client.updates.feature("some_feature", default=True)
if not access.allowed:
    print(access.message)
```

The types are in `vethuq.updates`: `UpdateResult`, `FeatureAccess` and the enums `UpdateStatus` and `UpdateCheckMode`.

### The result

The check compares the installed `vethuq` version with the policy's `pip` entry (PEP 440, so the policy's `1.2.0-rc.1` reads as `1.2.0rc1`):

| Installed version | `status` |
|---|---|
| at or above `latest` | `UP_TO_DATE`, nothing shown |
| below `latest`, at or above `minimum_supported` | `AVAILABLE` |
| below `minimum_supported` | `BELOW_MINIMUM`: reported, never snoozed or skipped |
| no signed policy yet (the baseline), offline, or a version that can't be compared | `UNKNOWN`, nothing shown |
| the check is switched off | `DISABLED` |

An `UpdateResult` has `status`, `mode`, `current`, `distribution`, `latest`, `minimum_supported`, `release_notes_url`, `snoozed`, `skipped`, `disabled_by_environment` and `policy_update_required`, plus:

| Property | Meaning |
|---|---|
| `notify` | Whether to tell the user now (not when disabled, snoozed, or the version is skipped; always when below the minimum) |
| `offer_install` | Whether a front end that can install updates should offer to: `notify` and the mode is `ON` |
| `message` | One line for the user; empty when there is nothing to say |

It also has `to_dict()` and `to_json()`.

**Local work is never blocked.** Below the minimum, indexing, search and your data keep working; only features that need a newer VethuQ are held back, each with a clear message.

`status()` and `check()` never raise: a problem means `UNKNOWN`. If the database can't be read (it may be newer than this VethuQ supports, which is exactly when an update is needed), the check still runs with the default settings.

### Features that need a newer version

The policy's `features` can carry a `min_client` and a `message` for each feature. `client.updates.feature(name, default)` returns a `FeatureAccess`:

| Field | Meaning |
|---|---|
| `allowed` | Whether the feature is available to this version |
| `requires_update` | It is unavailable only because this VethuQ is too old |
| `message` | The policy's message, or a generic one naming the version needed |

`default` is what the feature does when the policy doesn't cover it, so an older VethuQ keeps what already works; a feature whose default is off, and that the policy turns on for newer versions, comes back `allowed=False, requires_update=True`. A flag with `enabled: false` is the remote kill switch and applies to every version at or above its `min_client`. `feature()` makes no request and never raises.

### When it runs

Nothing runs on `import vethuq` or when a client is created. The command line and the desktop app are expected to start `client.policy.refresh_in_background()` at startup; `client.updates.check()` refreshes on request and `client.updates.status()` uses what is saved. Installing an update from VethuQ is not part of this: the check only tells you.

## Database

`client.db` checks the database file for corruption. A database can be damaged by a crash, a full disk or a sync tool, and finding out early beats a confusing failure in the middle of something else.

```python
result = client.db.integrity_check()  # check now
if not result.ok:
    for message in result.errors:
        print(message)

client.db.integrity_check(quick=True)  # a faster, less thorough check
status = client.db.integrity_status()  # the last check, automatic or not; no new scan
```

The types are in `vethuq.db`: `Db`, `IntegrityCheckResult` and the enum `IntegrityCheckMode`.

An `IntegrityCheckResult` has:

| Field | Meaning |
|---|---|
| `ok` | The database passed |
| `errors` | SQLite's own messages when it didn't (a bad page, a broken index, ...); empty when `ok` |
| `checked_at` | When the check ran (UTC) |
| `quick` | It was a quick check |

It also has `to_dict()` and `to_json()`.

### Full and quick checks

- A **full** check (the default) runs `PRAGMA integrity_check`: it verifies every page and that every index matches its table. It takes about as long as reading the whole file, which is instant for a small database and noticeable for a large one.
- A **quick** check (`quick=True`) runs `PRAGMA quick_check`: faster, but it doesn't verify that index contents match their tables, so it can miss damage that only affects an index.

### When it runs by itself

Each time a client opens the database (on first use), the check runs according to the `IntegrityCheckMode` in the [database settings](#database-settings), and **it is always a full check**:

| Mode | At open |
|---|---|
| `AUTO` (the default) | Runs unless a full check already passed within the interval (one day by default) |
| `ENABLE` | Runs every time |
| `DISABLE` | Doesn't run |

A check that failed is never counted as done: in `AUTO` mode a damaged database is checked again at the next open. The result is saved, logged to the `database` log, and available from `integrity_status()`.

### A damaged database

If the automatic check fails, or SQLite can't read the file at all ("file is not a database", "database disk image is malformed"), opening the database raises `CorruptDatabaseError` (exit code 12) and nothing else touches the file. The message names the first problem and the hint says what to do:

```python
try:
    client.sources.list()
except vethuq.errors.CorruptDatabaseError as error:
    print(
        error
    )  # "...failed its integrity check: ... Run client.db.integrity_check() for the details..."
```

Once refused, the client keeps refusing (without scanning again) until you call `client.close()` or create a new client. A locked or read-only database is not treated as damaged.

`client.db.integrity_check()` and `integrity_status()` work on the file itself, not through the normal connection, so you can still run them on a database that VethuQ refuses to open. Restore a backup, or move the damaged file aside to start fresh.

### Housekeeping at open

Opening the database also permanently deletes the sources that were removed longer ago than the retention in the [source settings](#source-settings), so they don't pile up.

## Version

`client.version` tells you what this install is running. It reads only local information, so it never opens or creates the database.

```python
import vethuq

client = vethuq.VethuQ()

version = client.version
print(version.vethuq)  # 0.1.0
print(version.python)  # 3.13.1
print(version.db_schema)  # 1
print(version.to_json(indent=2))
```

It returns a `VersionDetails`:

| Field | Description |
|---|---|
| `vethuq` | The installed VethuQ version. It is the same as `vethuq.APP_VERSION` |
| `python` | The Python version |
| `platform` | The operating system and platform |
| `db_schema` | The database schema version this build reads and writes |
| `file_types` | The file types installed |
| `search_engines` | The search engines installed |
| `ocr_engines` | The OCR engines installed |
| `ocr_languages` | The OCR languages installed |
| `add_ons` | The add-ons installed |
| `bundles` | The bundles installed |

The last six are placeholders: they are empty tuples for now and will fill in as those features arrive. `to_dict()` and `to_json(indent=None)` give the same details as a dict or JSON, with these as lists.

Import `Language`, `Paths`, `VersionDetails` and `VethuQ` from `vethuq`. Everything about sources is in `vethuq.sources` (`Source`, `SourceFile`, `PurgeResult` and the enums `FileIndex` and the enums `SourceType`, `SourceStatus`, `FileStatus`, `SourceSortBy` and `SortOrder`), everything about logs is in `vethuq.logs` (`LogEntry`, `LogFile`, `Log` and its subclasses, and the enums `LogLevel`, `LogComponent` and `SortOrder`), everything about the database is in `vethuq.db`, everything about the policy is in `vethuq.policy`, everything about updates is in `vethuq.updates`, and the errors are in `vethuq.errors`. Everything else under `vethuq` is internal and may change without notice.

## Add-ons

Some features ship as separate, licensed add-ons (for example backups). VethuQ itself deploys no add-on, needs none and works the same without them. Installed add-ons are found by their entry point; nothing is imported until you ask.

```python
client = vethuq.VethuQ()

client.addons.list()  # [AddonInfo(id="backup", status=AddonStatus.LOADED, ...)]
client.addons.is_installed("backup")  # False if it isn't installed
client.addons.get("backup")  # AddonInfo or None

# An installed add-on's public classes are imported from vethuq.addons:
from vethuq.addons.backup import Backup

backup = Backup(client)
```

If the add-on isn't installed, the import raises `ModuleNotFoundError`, as for any missing package; check `client.addons.is_installed(...)` first if the add-on is optional. `from vethuq.addons.<id> import ...` and `import vethuq_addon_<id>` give the same classes.

An `AddonInfo` has `id`, `name`, `version`, `status` and `detail` (why it isn't running), plus `to_dict()` and `to_json()`. The `AddonStatus` enum is `LOADED`, `INCOMPATIBLE` (it needs another add-on API version) or `FAILED`. An add-on that fails to load never stops VethuQ.

### Add-on settings

`client.addons.settings("backup")` gives an add-on's settings (`get`, `set`, `reset`), kept in the VethuQ database as `addon.<id>.<name>` and usable on a database VethuQ refuses to open. Names are lowercase letters, digits and underscores.

### Language add-ons

An add-on can provide languages (add-on API 0.2.0, `Addon.languages()`). They show up in `client.languages` with no further setup; `vethuq-addon-english` is one, and VethuQ depends on it. See [Languages](#languages).

### Hooks

Add-ons are called at two points, best effort (a failing hook is logged and VethuQ carries on):

- **on open**: the database has been opened (schema ready, integrity checked);
- **before migration**: the database is about to move to a newer schema, so an add-on can snapshot it first.

Hooks run in the same process, on the thread that opened the database, so an add-on must not call back into the client from a hook. The contract is in the `vethuq-addon-api` package.

### Policy and licences

An add-on checks its own licence; VethuQ never tells it one is valid. The signed policy can switch an add-on off remotely (`addons.<id>.enabled`) and revoke licences (`revoked_licence_ids`); see `client.policy`.
