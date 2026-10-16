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

Every error VethuQ raises on purpose is a subclass of `vethuq.errors.VethuQError`. Catch that for any of them, `StartupError` for the failures that stop VethuQ from starting, `SourceError` for the source errors, `SettingsError` for the settings errors, `LogError` for the log errors, `IndexingError` for the indexing errors, `CreditsError` for the credit errors, `SearchError` for the search errors, `TierError` for the processing tier errors, or a specific subclass for one failure.

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
| `IndexingError` | 50 | Indexing | Root of the indexing errors below |
| `IndexAlreadyRunningError` | 51 | Indexing | An index run is already going |
| `IndexRunNotFoundError` | 52 | Indexing | There is no index run with that id |
| `IndexNotRunningError` | 53 | Indexing | `pause()`, `resume()` or `stop()` was called with no run going |
| `FileNotTrackedError` | 54 | Indexing | `reindex_file()` was given a file VethuQ doesn't track |
| `CreditsError` | 60 | Credits | Root of the credit errors below |
| `InvalidGrantError` | 61 | Credits | A credit grant or licence can't be redeemed |
| `TierError` | 80 | Tiers | Root of the processing tier errors below |
| `TierUnavailableError` | 81 | Tiers | The tier asked for is unknown, not installed, not ready, or can't run in this version |
| `SearchError` | 90 | Search | Root of the search errors below |
| `SearchUnavailableError` | 91 | Search | The search engine asked for is unknown or can't be used now |
| `SearchOptionError` | 92 | Search | A search option can't be honoured (`option` says which): an unknown normalizer or level, or one the engine can't change |
| `SearchQueryError` | 93 | Search | The engine can't search the query |
| `CreditsExhaustedError` | 62 | Credits | There aren't enough credits for the work (an index run ends as `WAITING_CREDITS` instead of raising it) |
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
# notes.docx FileStatus.UNSUPPORTED
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
| `UNSUPPORTED` | A kind of file VethuQ can't read yet. Supported: PDF, text, CSV and Markdown, and images with the image add-ons installed |

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

`client.languages` is about the languages VethuQ can read documents in. Languages come from **language add-ons**; English (`vethuq-addon-english`, free) is installed with VethuQ, so it is always there and enabled. Other languages arrive as add-ons you install (and, if licensed, hold a licence for). Telugu (`vethuq-addon-telugu`) is one: licensed, not installed with VethuQ, listed as unavailable until `Telugu(client).set_licence(token)`. Telugu text is searched by every engine; vowel signs and the virama stay with their letter.

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
client.languages.get(
    "te"
)  # one Language; raises LanguageUnavailableError if VethuQ doesn't know it
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

## Indexing

`client.index` reads sources into pages. A run finds the files of the sources, reads each one's text, and returns when it is over.

```python
run = client.index.run()  # every active source
run = client.index.run(source.id)  # one source (its id or its path)
run = client.index.run("~/docs/report.pdf")  # one file inside an active source
print(run.status, run.files_processed, "of", run.files_total, "files,", run.files_failed, "failed")
```

`run(target=None, *, workers=None)` is synchronous. It picks up new and modified files, files that failed before, and files that couldn't be read until an add-on was installed; files already indexed are left alone. A file that fails never stops the run: it becomes `FileStatus.ERROR` with its message in `list_files(..., detailed=True)`. A damaged file isn't retried; any other failure is retried `retry_attempts` times. A password-protected file is `UNSUPPORTED` until it changes.

Only one run goes at a time (`IndexAlreadyRunningError`). A run whose process died is found and marked failed at the next run, and the files it was reading are put back.

**How a page is read.** The file's own text comes first. A page with enough text (20 characters, 3 words) and no images worth reading is *native*: no OCR. A page with enough text and images is *mixed*: only the images are read, and their text is added. A page without enough text is *scanned*: the whole page is read. Text, CSV and Markdown files are one page of text each and are always native, however short: the page itself is never OCR'd. A picture a Markdown file links to on disk is read like the images of a mixed page, from the moderate phase on (the quick phase leaves it), and only if an installed add-on reads that format; otherwise it is skipped with a warning in the log and the text is indexed anyway. OCR is in phases (see *OCR*): quick reads upright pages with the mobile models, and its models are downloaded the first time they're needed. Files with the same content (SHA-256) are read once and share their pages, also across sources; a document read in another language is read again for its image pages and the text is merged. A source is read in its first language (its own, otherwise the default languages setting).

### Controlling a run

A run is synchronous, but it can be paused, resumed and stopped from another thread or another process: the request is kept on the run's database row, and the workers look at it between files, pages and angle passes.

```python
client.index.pause()  # stops taking new work at the next checkpoint and waits
client.index.resume()  # carries on
client.index.stop()  # after the file it is on; returns once the run is over (wait=False to not wait)
status = client.index.status()
status.paused, status.stopping, status.phase, status.current_files, status.workers_active
status.deepened_pages, status.unsupported_files
```

A stopped run ends as `IndexRunStatus.STOPPED` (`error` is `"Stopped."`). The file it was on goes back to pending with the pages it already has, so the next run carries on after them; pages already sent to a remote tier still come back. A stopped run is never started again by itself. All three raise `IndexNotRunningError` when no run is going. `status().phase` is the part of the run it is in: `quick`, `languages` (the other candidate languages), `moderate` or `deep`.

### Running again

| Method | What it does |
|---|---|
| `run(target=None)` | New, modified and failed files, and files an add-on can read now. |
| `restart(target=None)` | Only the files that failed last time (a file that changed counts as modified, not failed). |
| `reindex(target)` | Every file under `target` (a source, or a file in one), read again. |
| `reindex_file(file)` | One file, by path or document id, read again. Raises `FileNotTrackedError` for a file VethuQ doesn't track. |

All take `workers=`, `tier=`, `wait=`, `timeout=` and `languages=`, and return an `IndexRun` (`run.mode` is `run`, `restart`, `reindex` or `file`). Reading a file again replaces its pages as they are read and clears what the earlier read recorded about them (its quick read, its deeper phases and its details). The old pages stay searchable until they are replaced, and the file stays `INDEXED`; if reading it again fails, it keeps the pages it had and says so in its `index.error`. It costs credits again. It is how to use a new OCR phase, new models or another language on what is already indexed.

### Languages

`languages=` on a run (a language id or a list: `["en", "te"]`) reads the files in those languages for that run, instead of each source's own languages or the default languages setting; it is the way to redo a file whose language was guessed wrongly (`reindex_file(file, languages=["te"])`). An unknown or unusable language raises `LanguageUnavailableError` before anything is read.

With one candidate language that is the language. With several, the first (English, unless it is not among them) reads each file and its read is judged: it must be at least 0.80 confident (weighted by how much text each page has) and at least 0.60 of what it read must be in its own script (`LanguageSpec.script_ranges`), with at least 12 letters to judge by. A confident or empty read settles the language and the others are skipped. An unsure one keeps only its believable lines (at least 0.60 confident and half in its script) and queues the other candidates as passes. The passes run after every file's quick read and before the deeper phases (`status().phase == "languages"`): each reads the file's pages that needed OCR again in its language, upright, adds the lines that language read believably, and is charged at the additional-language rate. A page read in several languages is read by the deeper phases in each, keeping the lines in that language's script.

A file with a text layer is in the languages whose script its text contains, so a search by language (`search.run(..., languages=["te"])`) finds a native Telugu PDF too.

**Models.** The quick phase's models for each source's first language are fetched before the first file is read, so a missing connection is said once, up front; the run goes on (files with a text layer need no models, and the others fail with the reason). A failed download is remembered for 30 seconds, so a run does not try once per file or page. A deeper phase whose models can't be fetched is skipped for that language with a single warning.

### Progress and ETA

`client.index.status()` is where the latest run is, and how long it has left. It reads the database, so it works while `run()` is going in another thread or process; it is `None` if no run has ever started.

```python
status = client.index.status()
status.run  # the latest IndexRun, its counts live while it goes
status.active, status.remote_jobs_open, status.finished
status.eta.seconds  # the best estimate of the time left
status.eta.local_seconds, status.eta.remote_seconds, status.eta.complete, status.eta.by_file_type

status = client.index.status(wait=True)  # block until the run and its remote jobs are done
status = client.index.status(wait=True, timeout=30)  # ... or for up to 30 minutes
run = client.index.run(tier="github")
run.eta  # what is still outstanding: for example the jobs away on GitHub
```

`wait=True` waits for the run (here or in another process) to end, then asks the remote tier about the jobs it sent and takes in their results as they finish, until none is out (or the time is up: you get the status as it is then). Without a `timeout` a run is waited for as long as it goes and remote jobs for `settings.tiers`' wait time. A run whose process died is marked failed.

The ETA comes from what earlier runs took on this computer, so it exists before the first file is done:

- **Pages read here.** The files still to do, by file type, times how many pages a file of that type has and how many of them needed OCR (from the files indexed most recently), times the seconds an OCR page took (`usage_daily`, last 30 days; all time for a type with nothing recent), divided by the run's workers. Native text, and file types read straight from disk, cost nothing.
- **Pages away on a remote tier.** Jobs run side by side, so the slowest one counts: what the tier usually takes from submitted to completed (its last 30 days of jobs, else all time) less the job's age, never below 0. A run that still has pages to send adds one more such batch. The remote tier reads the pages, so they add nothing to the local time.
- `complete` is `False` when part of the work has no history (a file type or tier never used); `seconds` then leaves that part out. It is a guess, not a promise. A `hybrid` run counts its pages as read here plus the jobs it has out.

### Index runs

An `IndexRun` has `id`, `source_id`, `target` (the source's path, or the file's; `None` for a run of every source), `file_path`, `status` (`IndexRunStatus`: running, completed, stopped, failed), `files_total`, `files_processed`, `files_failed`, `workers`, `started_at`, `completed_at`, `error`, `eta` (only on what `run()` returns: the time still outstanding, see below) and `to_dict()` / `to_json()`.

```python
client.index.get(run.id)
client.index.history()  # newest first
client.index.history(source.id, status="failed", limit=10)
client.index.history(
    started_after=datetime(2026, 1, 1),  # naive means UTC; ISO strings work too
    sort_by=IndexRunSortBy.FILES_FAILED,
    order=SortOrder.DESC,
)
```

`history(target=None, status=None, started_after=None, started_before=None, sort_by=IndexRunSortBy.STARTED_AT, order=SortOrder.DESC, limit=None, offset=0)`. `target` is a source (id or path) or a file. `get` raises `IndexRunNotFoundError`. Purging a source deletes its runs.

### What list_files shows

`client.sources.list_files(source, detailed=True)` adds to each file's `FileIndex` the `pages` read, their average `confidence` (0 to 1), the `languages` it was read in and its `file_type`.

### Web file types (licensed)

HTML (`.html`, `.htm`, `.xhtml`), XML (`.xml`, `.xsd`, `.xsl`, `.xslt`), RSS and Atom feeds (`.rss`, `.atom`), CSS, JavaScript (`.js`, `.mjs`, `.cjs`) and JSON come from licensed add-ons (`vethuq-addon-html`, `-xml`, `-rss`, `-css`, `-js`, `-json`), not installed with VethuQ: `pip install vethuq[web]` installs the web pack bundle (`vethuq-bundle-web`). They are read straight from disk, never OCR'd and never charged for. Until a licence is installed (`Html(client).set_licence(token)`; one web pack licence unlocks all five) the types are listed in `client.file_types` as unavailable with the reason and their files are not indexed; they are picked up as newly readable once it is. Each type keeps its own facts in a table beside `pdf_pages`: `html_pages` (encoding, title, lang, link and local image counts), `xml_pages` (root, element and attribute counts, whether it was well formed), `css_pages` (rules, local images), `js_pages` (lines, comment lines) and `json_pages` (kind, values, depth). HTML and CSS point at the local pictures they use, which the moderate OCR phase reads.

### Developer file types (licensed)

Source code (`.py`, `.java`, `.ts`, `.tsx`, `.jsx`, `.cs`, `.go`, `.rs`, `.php`, `.rb`, `.sh`, `.ps1`, and `.js`, `.mjs`, `.cjs`) comes from one licensed add-on per extension (`vethuq-addon-py`, `-java`, ..., `-js`) in the developer pack bundle, kept as text with blank lines dropped, and Jupyter notebooks (`.ipynb`) from `vethuq-addon-ipynb` (the cells and their text output). INI (`.ini`), SQL (`.sql`), reStructuredText (`.rst`) and log (`.log`) files come from the licensed `vethuq-addon-ini`, `-sql`, `-rst` and `-log`, in the same developer pack bundle: INI is flattened to `section.key: value` lines, SQL and logs are indexed as written (a log is cut at 64 MB, at a line end), and reStructuredText as prose without its markup. TOML (`.toml`) comes from the licensed `vethuq-addon-toml`, in the same developer pack bundle; it is parsed with `tomllib` and flattened into `path: value` lines like YAML (`package.authors[0]: Ada`). YAML (`.yaml`, `.yml`) comes from the licensed `vethuq-addon-yaml`, which `pip install vethuq[developer]` installs with JSON in the developer pack bundle (`vethuq-bundle-developer`; JSON is also in the web pack). Every document of a YAML stream is read with the safe loader and flattened into `path: value` lines (`server.ports[0]: 8080`); `on`, `off`, `yes` and `no` stay words, and an alias bomb is refused. Its table is `yaml_pages` (encoding, document, value and depth counts). Licensing works as for the web file types: one developer pack licence unlocks both.

MHTML web archives (`.mhtml`, `.mht`) come from the licensed `vethuq-addon-mhtml` (`pip install vethuq-addon-mhtml`; not in a pack bundle yet), set up with `Mhtml(client).set_licence(token)`. A saved page is read like an HTML file, plus its address and the text of frames saved inside it; the pictures in the archive are read with OCR from the moderate phase, and nothing is fetched from the web. The web interface shows the archive as the page it was (pictures, styles and saved frames in place) or as its source.

NDJSON / JSON Lines (`.ndjson`, `.jsonl`) comes from the licensed `vethuq-addon-ndjson` (`pip install vethuq-addon-ndjson`; not in a pack bundle yet), set up with `Ndjson(client).set_licence(token)`. Each line is flattened to `path: value` lines like a JSON file, with a blank line between records; a line that is not valid JSON is skipped and counted, and the file is read a line at a time, so a large log is fine.

Parquet (`.parquet`, `.pq`) comes from the licensed `vethuq-addon-parquet` (`pip install vethuq-addon-parquet`; it is not in a pack bundle yet), set up with `Parquet(client).set_licence(token)` like the other licensed file types. A table is indexed as text: a line of column names, then a line per row with something in it; it is read a batch of rows at a time and never OCR'd. The web interface shows the file as a table, in the CSV table preview, opened on the matching row and cell.

**The data pack.** `pip install vethuq[data]` installs `vethuq-bundle-data`, which brings CSV, TSV, Parquet, JSON and NDJSON together. Parquet, JSON and NDJSON are licensed and one data pack licence unlocks all three; CSV (installed with VethuQ anyway) and TSV are free and need none.

### Office file types (licensed)

`pip install vethuq[email]` installs just the two email file types (`.eml`, `.msg`; `vethuq-bundle-email`, also part of the office pack). The OpenDocument formats of LibreOffice and OpenOffice (`.odt`, `.ott`, `.ods`, `.ots`, `.odp`, `.otp`) come from licensed add-ons (`vethuq-addon-odt`, `-ott`, `-ods`, `-ots`, `-odp`, `-otp`), installed by the open office pack bundle (`pip install vethuq[open-office]`; one licence unlocks all six). Word (`.docx`, `.doc`, and the templates `.dotx`, `.dot`), Excel (`.xlsx`, `.xls`, and `.xlsm`, `.xlsb`), PowerPoint (`.pptx`, `.ppt`, and `.pptm`, `.ppsx`, `.pps`), RTF and email (`.eml`, and Outlook `.msg`) come from licensed add-ons (`vethuq-addon-docx`, `-doc`, `-xlsx`, `-xls`, `-pptx`, `-ppt`, `-rtf`, `-eml`, `-msg`, `-dotx`, `-dot`, `-xlsm`, `-xlsb`, `-pptm`, `-ppsx`, `-pps`), not installed with VethuQ: `pip install vethuq[office]` installs the office pack bundle (`vethuq-bundle-office`), and one office pack licence unlocks all sixteen (`Docx(client).set_licence(token)`). The text is read straight from the file, never OCR'd and never charged for: Word paragraphs, tables, headers and footnotes; each Excel sheet by name with its rows; slides, notes and comments; an email's headers and body (attachments are left out). Pictures embedded in a Word, Excel, PowerPoint or RTF file are read with OCR from the moderate phase on. Each type has a table of its own beside `pdf_pages` (`docx_pages` ... `rtf_pages`: line and picture counts; `eml_pages`: subject, sender, recipients, sent date, message id).

### Commands from add-ons, and `may_ocr`

`client.addons.cli()` lists the command groups installed add-ons describe with `Addon.cli()` (add-on API 0.11.0); the `vethuq-cli` package mounts them as `vethuq <group> ...` and their settings under `vethuq settings addons <group> ...`. A file type's reader can say `may_ocr = False` (text read straight from the file): a run that only has such files never fetches the OCR models.

### Queued requests and the background service

`index.queue.submit(target, mode="run"|"restart"|"reindex"|"file", ...)` writes a request that a worker takes later; `list()`, `get()` and `cancel()` look after it (`IndexJob`, `IndexJobStatus`). A worker calls `claim_next()` / `run_next()`, which runs the oldest request with the same `index.run(...)` a person calls, closes it (`completed`, `failed`, `cancelled`) and records the run; a request a dead worker had taken is put back. A worker marks that it serves the data folder (`announce_service()`), so `service_running()` tells index commands to queue their work. `status().queued_jobs` counts the waiting ones. The `vethuq-background` package is such a worker: a systemd user unit or a Windows service.

### Run health, and rebuilding the search index

A running run refreshes a heartbeat every few seconds. `index.status()` carries `heartbeat_at` and `stalled`: `stalled` is true when the run's process is alive but has been quiet for two minutes, i.e. it is hung (end the process from outside, then `index.clear_stale()`). A run that starts after another was left behind by a process that ended first runs a full database integrity check, whatever the integrity schedule says; a damaged database raises `DatabaseIntegrityError` (a `CorruptDatabaseError`) and nothing is changed. `search.rebuild()` rebuilds the search index from the stored page text (no file is read again). It raises `IndexAlreadyRunningError` while a run is going and returns a `SearchIndexRebuildResult` (`pages`, `seconds`, `ok`, `error`); a failure is in the result, not raised.

### Formatting

`vethuq.formatting.Formatting` has the small formatters front ends and reports share: `size(bytes)` (`1.5 KB`), `seconds(s)` (`2.5s`), `duration(s)` (`3m 5s`), `timestamp(iso)` (local time, `2026-10-04 12:30:05`) and `short_timestamp(iso)` (`4 Oct 2026 12:30`). A missing value renders as `-`. HTML exports use it for file sizes.

### Search option defaults

An engine declares its own options (`client.search.engines()` lists them with their defaults and choices). `client.settings.search.set_option("fuzzy", "threshold", "loose")` saves a default for one; `get_option` returns it (the engine's own default until one is saved) and `reset_option` forgets it. A search's own `options=` always wins, and a saved value the engine no longer allows is ignored. Core knows no engine by name: whichever engine add-on is installed (fuzzy, semantic, proximity, noise-fuzzy) gets this for its options.

### Index settings

```python
client.settings.index.set_workers("auto")  # "auto" (the default) or 0 to 8; 0 = this thread
client.settings.index.set_retry_attempts(3)  # the default
client.settings.index.set_stability_check_seconds(1.0)
```

`settings.index.set_stale_lock(mode)` decides what a new run does about a run left behind by a process that ended: `auto` (the default) and `enable` fail it, put its files back and carry on; `disable` refuses to start with `IndexAlreadyRunningError` until `index.clear_stale()` clears it (it returns how many runs it cleared and never touches a run that is really going).

`settings.ocr.set_gpu(True)` asks OCR engines to use the GPU (off by default; `get_gpu`, `reset_gpu`). An engine that can't falls back to the CPU and the log says so. It applies to engines started after the change.

With `auto`, VethuQ reads as many files at once as it estimates the machine can carry. The licensed `vethuq-addon-autoscale` add-on does better: it watches the machine's CPU and memory while the run goes, learns from what earlier files took (kept, without names or paths, in `file_footprints`) and raises or lowers the number as the run goes, never above VethuQ's estimate and never to zero. It is asked only when `workers` is `auto`; with a number set, or without a licence, the static estimate is used and nothing changes. `status().workers_active` shows how many files are being read now.

Each also has a `get_...` and `reset_...`. The stability check waits once per run so files still being written are read as they end up; 0 turns it off.

## File types

`client.file_types` lists the kinds of file VethuQ can read. They come from add-ons; PDF (`vethuq-addon-pdf`), text (`-txt`), CSV (`-csv`) and Markdown (`-markdown`) are installed with VethuQ. Text, CSV and Markdown files are read straight from disk, never OCR'd and never charged for. TSV files (`vethuq-addon-tsv`, tab-separated values) are read the same way, from a free add-on that is not installed with VethuQ: `pip install vethuq[tsv]`. Image files (PNG, JPG, TIFF, BMP, GIF, WebP, JPEG 2000, SVG; an SVG's text is read straight from the drawing, never OCR'd) come from free add-ons that are not installed with VethuQ: `pip install vethuq[images]` installs them (`vethuq-bundle-image`). HEIC photos (`.heic`, `.heif`, `.hif`) come from `vethuq-addon-heic`, which the bundle installs too (its pillow-heif dependency ships wheels that include GPLv2 libx265). An image is read with OCR and priced by its pixels, and with the add-ons installed the pictures a Markdown file links to are read too.

```python
client.file_types.list_all()  # every file type, with `available` and `enabled`
client.file_types.list_enabled()  # the ones that are read: available and enabled
client.file_types.defaults()  # the ones installed with VethuQ: csv, markdown, pdf, txt
client.file_types.get("pdf")  # a FileType; raises FileTypeUnavailableError if none is installed
client.file_types.disable("pdf")  # files of this type are skipped from now on; indexed ones stay
client.file_types.enable("pdf")  # back on (it must be available)
```

## OCR

`client.ocr` shows what reads scanned pages, all provided by add-ons: the engine (`vethuq-addon-paddle`) and the quick phase (`vethuq-addon-ocr-quick`) are installed with VethuQ; the deeper phases, `vethuq-addon-ocr-moderate` and `vethuq-addon-ocr-deep`, are optional installs (`pip install vethuq[deep-scan]`, the `vethuq-bundle-deep-scan` bundle).

```python
client.ocr.engines.list()  # [OcrEngine(id="paddle", profiles=("mobile", "server"), available=True, ...)]
client.ocr.phases.list()  # [OcrPhase(id="quick", angles=(0,), profile="mobile", ...), moderate, deep]
```

### Phases and angles

Text at an angle (a label on a drawing, a stamp, a sideways caption) is often missed by a single upright read, but reading every page at many angles is slow. So OCR is split into phases, each of which adds to what the ones before found:

| Phase | Angles (counter-clockwise) | Models |
|---|---|---|
| `quick` | 0 | mobile |
| `moderate` | 90, 180, 270 | server |
| `deep` | every other multiple of 15 (15, 30, 45, ...) | server |

`client.settings.ocr` says how far a run goes (`get/set/reset_engine`: `"quick"` unless changed). `index.run()` reads every file quick first, then continues with moderate and deep up to the setting; a file is searchable after its quick pass. Every few seconds it looks for new or changed files and, if there are any, reads them (quick) before going on: quick, then moderate, then deep, in that priority. A phase whose add-on is not installed is skipped with a warning in the log.

- **What is turned.** Only pages that needed OCR: a scanned page (the whole page), or the images on a page that has a text layer. Native text, and the text, CSV and Markdown files, never are. A picture a Markdown file links to is read from `moderate` on, upright as well (the quick phase left it) and at 90, 180 and 270; `deep` adds the rest.
- **Merging.** A line a rotated read adds must be at least 0.5 confident (odd angles read strokes as text). A line the page already has is dropped, and a line inside a new, longer one is replaced by it. The page's confidence follows its lines. Each phase read is recorded per page and language (`pdf_pages_phases`), saved as soon as the page is read, so a run that stops loses nothing; a second run reads only what is missing.
- **Credits.** A phase is charged only when it runs on a page: each rotated read costs the page's size factor times the rotated rate (0.8 by default) per image, so moderate adds 3 x 0.8 and deep 20 x 0.8 for an A4 page, and a page read in two languages is charged for each. When they run out, the run ends as `WAITING_CREDITS`.
- **Remote tiers.** The GitHub tier takes the deeper reads as well: the image is sent once, with the angles to read it at, and the worker turns it with the same server models (baked into its image). A hybrid run sends a deeper read to GitHub when `settings.tiers` `phases` lists its phase (or the page is large).
- **ETA.** `index.status().eta` adds the pages still waiting for each phase the setting reaches, times that phase's angles, times how long a pass took before (`eta.by_phase`). Pages the quick phase has not read yet are not counted: whether they need OCR is not known until they are read.

### OCR models

Models are downloaded automatically the first time a page needs them, into `<data root>/models`. `client.ocr.models` lets you see and manage them; `languages` is a list of language ids (left out: all).

```python
models = client.ocr.models
models.cache_dir  # where they are kept
models.list()  # [OcrModel(name, engine, kind, shared, languages, installed, path, size_bytes)]
models.download(on_progress=lambda name, state: print(name, state))  # fetch ahead of time
models.redownload(["PP-OCRv5_mobile_det"])  # delete and fetch again
models.clear(["te"])  # delete the models only Telugu uses
models.clear(["te"], include_shared=True)  # ... and the shared ones
models.clean()  # delete models no installed language needs
```

`download` and `redownload` raise `OcrModelMissingError` for any model that couldn't be fetched.

## Processing tiers

VethuQ always extracts a file's pages and decides, on your computer, which need OCR. A **processing tier** decides where that OCR runs.

| Tier | Where | Wallet |
|---|---|---|
| `local` (the default, always there) | on this computer | `local` |
| `github` | in your own GitHub account (the GitHub add-on) | `github` |
| `hybrid` | local first; the pages the settings pick (large ones, later the deeper OCR phases) go to GitHub | `local` and `github` |

```python
client.tiers.list()  # [Tier(id="local", available=True, selected=True, ...), ...]
client.tiers.set("github")  # make it the default (it must be a tier VethuQ knows)
client.tiers.current()
client.tiers.reset()  # back to local
client.index.run(tier="local")  # or name it for one run
client.credits.wallets()  # ["local", "github"]: the wallets of the tiers you can use
client.credits.balance("github")
```

A `Tier` has `id`, `label`, `wallet`, `available`, `reason` (why not), `selected` and `remote` (its work finishes later). An unavailable tier can be chosen, but a run with it raises `TierUnavailableError` saying why; nothing falls back silently. `hybrid` is available when `github` is. `IndexRun.tier` records the tier a run used.

Tiers come from add-ons (`Addon.processing_tiers()` in the add-on API 0.4.0): each brings an `OcrExecutor` that reads images, either at once (`recognize`) or as a batch that finishes later (`submit`, `poll`, `collect`). Each tier is paid from its own wallet; the GitHub wallet gets 20 credits a day for a private runner repository and 200 for a public one, and the metrics bonus applies to it as it does to `local`.

**Hybrid.** `client.index.run(tier="hybrid")` reads pages that need OCR here, except the ones the router sends to GitHub: a page whose size against A4 is at least `settings.tiers` `min_size_factor` (2, an A3 sheet, by default; 0 turns the rule off), or whose OCR phase is in `phases` (the deeper `moderate`/`deep` phases, once they exist; none by default). Each page is paid from the wallet of the tier that reads it (`local` or `github`). A page GitHub can't take (its wallet can't pay) is read here instead, and the run ends `WAITING_REMOTE` while the sent pages are away, as with `github`. Hybrid needs the `github` tier to be available; the `github` tier comes from the [GitHub add-on](#github-runner). The credit estimate doesn't split by tier.

### Tier settings

### Remote jobs

A tier whose work finishes later (an asynchronous executor, such as the GitHub add-on) works in jobs. `index.run(tier=...)` reads and renders the pages, keeps native text, and for the pages that need OCR pays for the images (from that tier's wallet), saves the page as waiting, and sends the images in batches of at most `max_job_pages` pages and `max_job_megabytes`. The run then ends as `IndexRunStatus.WAITING_REMOTE`: nothing waits for GitHub unless you ask (`wait=True, timeout=minutes`, default from `settings.tiers`).

```python
run = client.index.run(tier="github")  # WAITING_REMOTE when images are away
client.index.jobs(status="submitted")  # [RemoteJob(id, run_id, tier, status, images, credits, ...)]
client.index.collect()  # take in what has finished; returns the jobs that ended
client.index.collect(wait=True, timeout=30)  # ... or keep asking for up to 30 minutes
```

`RemoteJobStatus`: `submitted`, `completed`, `failed`, `expired`. Every `index.run()` first collects jobs left by earlier runs, and again at its end. A finished job's pages are saved and files whose pages have all arrived become `INDEXED` (the run that sent them completes). A job the tier says failed, or that is out for more than 24 hours, is **given back**: its images' credits are refunded and its pages wait to be sent again by the next run. An image that comes back empty is treated the same. A run that dies before sending leaves paid-for images that the next run refunds and sends again. Running again while a job is out sends nothing twice; those files show as `PROCESSING`.

`client.settings.tiers`: `get/set/reset_min_size_factor` (from what page size, against A4, hybrid sends a page to GitHub; 2 = A3; 0 turns the rule off), `get/set/reset_phases` (the OCR phases hybrid sends: `moderate`, `deep`; none by default), `get/set/reset_wait_timeout_minutes` (60), `get/set/reset_max_job_pages` (200) and `get/set/reset_max_job_megabytes` (200).

## Credits

Reading pages costs credits; searching and everything else is free. **One credit is the work of reading one A4 page once, upright, in one language.** Pages that need no OCR (native text), duplicate files and unchanged files cost nothing. A page's price is its size against A4 (reduced by 5%, rounded up to a quarter, at least 0.25, and nothing above A0), times the pass rate. A page that is partly text is charged for the share of it the images cover (at least 0.25), a blank page costs 0.25, and a page that couldn't be read (or whose remote job failed) is refunded. The numbers come from the signed policy (`rate_card`, `wallets`, `caps`) and fall back to built-in defaults offline; a policy change applies from the next UTC day. The full rules are in `docs/credits.md` of the support repository.

The free **local wallet** gets 500 credits a day (reset at 00:00 UTC, no rollover) and a one-off 2,000 starter. Spending order: promotional, daily (with the metrics bonus), scoped one-off, general one-off.

```python
balance = client.credits.balance()  # a wallet: balance("github")
print(balance.daily, balance.one_off, balance.total, balance.next_reset)

estimate = client.credits.estimate("~/docs")  # reads the files, changes nothing
if estimate.affordable:
    client.index.run("~/docs")

client.credits.history(kind="charge", source=1, limit=20)  # the ledger
client.credits.redeem([{"id": "LIC-1-g1", "amount": 250}])  # a licence's grants, once each
client.credits.redeem_licence(token)  # verify with vethuq-entitlements, then redeem
```

`CreditBalance` has `daily`, `promotional`, `one_off`, `total`, `daily_allowance`, `bonus_active`, `bonus` and `next_reset`. `history(kind=None, source=None, run_id=None, since=None, until=None, sort_by=CreditSortBy.AT, order=SortOrder.DESC, limit=None, offset=0)` gives `CreditEntry`s (`CreditEntryKind`: grant, charge, refund, expire); charges are written page by page, so the balance is always the latest. Purging a source deletes the charges made for it; the balance is not affected. Everything has `to_dict()` and `to_json()`.

**Running out.** Pages are paid for as they are read. When the wallet can't cover the next page the run stops as `IndexRunStatus.WAITING_CREDITS`: files already indexed stay indexed, and the file in progress keeps the pages it read (saved and paid for) and waits as `PENDING`. The next `index.run()` after the reset carries on with the page after the last one saved.

**Add-on wallets.** An add-on that does paid work has a sub-wallet named after it, listed in `client.credits.wallets()` (`semantic` is the first). It is separate from `local` and `github`: nothing is spent from one for another's work. Its daily allowance and price come from the policy (`wallets.addons.<id>`, `rate_card.semantic`), and an add-on spends from it through `Host.credits` (add-on API 0.6.0).

A licence can carry credit grants (`vethuq-admin licence issue --grant 250`): each grant has an id, an amount, an optional add-on scope and an expiry, and is added once however often it is redeemed. A grant scoped to an add-on that has a sub-wallet (`semantic`) tops up that wallet; any other scope is local credit that only that work can spend. The policy's `caps.one_off_max` limits what you can hold.

## Statistics

`client.stats` shows the work done: processing and confidence. It is built from daily totals kept as pages are read (never names, paths or text), so it survives file changes and purged sources (those show as "(purged source)").

```python
overview = client.stats.overview()  # one row per source, plus the total
overview = client.stats.overview(
    StatsGroupBy.DAY,  # source, language, file_type, engine,
    language="en",
    since="2026-10-01",  # page_source, band or day
    band="low",
    sort_by=StatsSortBy.CREDITS,
    order=SortOrder.DESC,
    limit=10,
)
overview.total.pages, overview.rows[0].pages_per_minute

client.stats.source(1)  # one source's totals (removed ones too)
client.stats.failures()  # {"password": 2, "corrupt": 1, ...} by reason code
client.stats.low_confidence_pages()  # the pages OCR wasn't sure of, least sure first
```

`overview(group_by=StatsGroupBy.SOURCE, *, source, language, file_type, engine, page_source, band, since, until, sort_by=StatsSortBy.KEY, order=SortOrder.ASC, limit, offset)`: the filters keep matching work only; `since` and `until` are UTC days; the total always covers every matching row. A `StatsRow` has `key`, `files` (indexed now; by source only), `pages`, `native_pages`, `ocr_pages`, `passes`, `confidence` (0 to 1), `bands`, `duration_ms`, `ms_per_ocr_page`, `pages_per_minute`, `credits` and `failures` (by source, file type or day).

**Confidence bands.** `high` from 90%, `medium` from 80%, `low` from 70%, below that `unreliable`; native pages are 100%. Change them with `client.settings.confidence.set_bands(70, 80, 90)`. `list_files(detailed=True)` shows each file's `band` and `low_confidence_pages`, and takes `min_confidence` (0 to 1) and `band` to filter.

## Metrics sharing

Off unless you turn it on (`client.metrics.opt_in()`). When on, aggregated, content-free statistics (timings, confidence, phases, languages, engine, settings used, failure reasons, size buckets, rough hardware) are sent to the collector the policy names (`metrics.endpoint`), at the end of an index run, at most once a day. Never file names, paths, content, OCR text, search text, user names, licence ids or anything derived from your computer; the batch carries a random install id so the data can be deleted. In return the local wallet's daily credits go up by 10% (`metrics.bonus_percent`, at most 15%) while sharing is on and a batch was sent in the last 7 days, from the UTC day after a send. The bonus changes what you have, never what a page costs.

```python
client.metrics.status()  # opted_in, available, last_sent_at, pending_days, bonus_active ...
client.metrics.preview()  # exactly what would be sent next
client.metrics.send()  # now (forced with send(force=True)); never raises
client.metrics.opt_out()
client.metrics.delete_data()  # asks the collector to delete everything for this install
```

Only closed UTC days are sent, each once. The schema is in the VethuQ repository (`metrics/schema/v1`) and so is the collector (`metrics/collector`, a Cloudflare Worker); anything not in the schema is refused by both.

## Search

`client.search` finds text on the pages that were indexed. Only pages of files that are `indexed` and whose text is final are searched. Search engines and the normalizers they apply come from add-ons, all free. `exact`, `like` and `full-text` are installed with VethuQ; `lexical`, `proximity`, `fuzzy` and `noise-fuzzy` are not, and each is installed with its own extra (`pip install vethuq[lexical]`, `vethuq[proximity]`, `vethuq[fuzzy]`, `vethuq[noise-fuzzy]`). Installing `fuzzy` or `noise-fuzzy` also installs the `leetspeak` normalizer, and `pip install vethuq[search]` installs every engine and normalizer at once:

| Engine | Finds | Strictness |
|---|---|---|
| `exact` | the query as typed, as a whole word, always case-sensitive | 10 |
| `like` | the query anywhere in a page, even inside a word | 20 |
| `lexical` | the same, with pages ranked by relevance (BM25); at least 3 characters | 30 |
| `proximity` | all of the query's words within N words of each other, in any order | 40 |
| `full-text` | whole words and `"phrases"` (`mus*` is a prefix), with English word forms, ranked by relevance | 50 |
| `fuzzy` | words close to the query's: misspellings and OCR misreads | 60 |
| `noise-fuzzy` | words hidden by stray characters, look-alikes and typos (`h3ll0`, `h.e llo`) | 70 |
| `semantic` | passages that *mean* what the query means, in about a hundred languages (`pip install vethuq[semantic]`) | 80 |

and the normalizers `case` (`match`, `ignore`), `unicode` (`off`, `basic` composes characters, `full` also folds accents and compatibility forms: `cafe` finds `café`, `ﬁne` is `fine`) and `leetspeak` (`off`, `basic`, `standard`, `extended`: `h3ll0` is `hello`). `semantic` is free to use but **credit based**: preparing pages costs credits from its own wallet (see [Semantic search](#semantic-search)).

```python
result = client.search.run("invoice")  # every engine; hits found by several say so
for match in result:
    print(match.file_path, match.page_number, match.before, match.matched, match.after)

client.search.run("Museum", engine="exact")
client.search.run(
    "cafe", engine="like", normalize={"unicode": "full"}
)  # or "unicode=full,case=match"
client.search.run("mus", case_sensitive=True, limit=20, offset=40, languages="en")
```

`run(query, *, engine=None, normalize=None, case_sensitive=None, context_chars=None, languages=None, options=None, combine=None, sort=None, order="asc", limit=None, offset=0)` returns a `SearchResult`: `matches` (the page asked for), `total`, `engine`, `levels` (the level each normalizer ran at, per engine), `index_rebuilt` and `pending` (per engine, pages it can't search yet: see [Semantic search](#semantic-search)). A `SearchMatch` has the file (`file_id`, `file_name`, `file_path`, `duplicate_of_path` for a file with the same content as an earlier one), the page (`page_number`, `total_pages`, `source`), the text (`before`, `matched`, `after`, `truncated_before`, `truncated_after`, `start`, `end`), and `engine`, `matched_by` (every engine that found it, strictest first), `score` and `modifiers` (`accents` when a match needed the Unicode folding). Highlights always show the original text. An empty query matches nothing. `SearchResult`, `SearchMatch` and the rest have `to_dict()` and `to_json()`.

**Engine options.** Some engines have settings of their own that a search can override, by engine id: `options={"fuzzy": {"threshold": "loose"}}` or `options="fuzzy.threshold=0.7,proximity.distance=3"`. `fuzzy` takes `threshold` (`strict`, `balanced`, `loose`, or 0.5 to 1), `proximity` takes `distance` (`tight`, `medium`, `loose`, or 1 to 100 words), `noise-fuzzy` takes `threshold`, `leetspeak` (`off`, `basic`, `standard`, `extended`; it carries its own look-alike tables) and `noise` (`low`, `medium`, `high`), `semantic` takes `threshold` and `limit` (`client.search.engines()` lists them with their defaults). Each is also a setting of its add-on (`client.addons.settings("fuzzy")`). An option the engine doesn't have, a value it doesn't allow, or one for an engine that isn't in the search raises `SearchOptionError`.

**Ranking.** `sort="path"` (the default) orders by file, page and position; `sort="score"` by the engines' own scores; `sort="rank"` puts the best match first *across* engines. The engines answer different questions, so their scores can't be compared: pages are ranked by how strict the strictest engine that found them is (`exact`, `like`, `lexical`, `proximity`, `full-text`), what a normalization was needed for ranks below what matched as typed, the approximate engines (`fuzzy`, `noise-fuzzy`, `semantic`) come last, and within a tier an engine's own signal (relevance, similarity, or how many matches) orders the pages. In the `all` search, hits of different engines that overlap are one match, labelled with the strictest engine and listing every engine in `matched_by`. Ranking lives in VethuQ, not in an add-on, because only VethuQ sees every engine's hits: an engine added later is ranked by its `strictness` and `approximate` alone.

**What counts as the same character** is a normalizer's level. For each normalizer an engine uses, the level is: the one asked for in this search (`normalize`, or `case_sensitive`), else the one the engine fixes, else the level you saved (`settings.search`, where the engine takes it), else the engine's own default. `like` ignores case and composes Unicode (`basic`); `exact` always matches case, composes Unicode, and takes a different Unicode level only when a search asks for it, never from the saved setting. Naming one engine and asking for what it can't do (`exact` with `case_sensitive=False`, a normalizer it doesn't use, an unknown level) raises `SearchOptionError`; in the `all` search an engine just doesn't apply what it can't.

```python
client.search.engines()  # SearchEngineInfo: id, label, available / reason, in_all, selected, normalizers, options, approximate
client.search.normalizers()  # NormalizerInfo: id, levels, identity, version, setting
client.search.status()  # SearchIndexStatus: pages_indexed, pages_total, current, full_text
client.search.rebuild()  # build the index again from the stored page text
client.search.sync("semantic")  # prepare pages for engines that need it (see below)
```

A normalizer an engine merely *can* use (`like` and `fuzzy` take `leetspeak`) is optional: the engine works without that add-on installed, it just can't be asked to use it.

**The index.** VethuQ records each finished page's text in the coarsest form the installed normalizers allow (case folded, accents dropped), and keeps an SQLite FTS5 trigram index over it (`page_search`, `page_search_fts`), so a search only reads the pages that can match; the engine still checks each one. The index is brought up to date after an index run and before a search. A page whose text changes loses its entry and gets a new one. It is stamped with the names and versions of the installed normalizers: when they change (an add-on installed, removed or upgraded) the first search rebuilds it, and `SearchResult.index_rebuilt` says so. Queries shorter than 3 characters, and SQLite builds without the trigram tokenizer, narrow pages with a plain substring test on the index instead.

### Semantic search

`semantic` finds passages by meaning: "refund policy" finds "customers may return goods for a full reimbursement", and a Telugu query finds the English page that says the same thing. It reads each page into vectors with a small multilingual model (`intfloat/multilingual-e5-small`, downloaded once, like the OCR models), so the work is **preparing pages**, done ahead of searches:

```python
reports = client.search.sync("semantic")  # downloads the model, then embeds the pages that need it
print(reports[0].pages, reports[0].pending, reports[0].credits, reports[0].paused)

result = client.search.run("refund policy", engine="semantic")
print(result.pending)  # {"semantic": 12}: pages not prepared yet, so not searched
client.search.run("refund policy", engine="hybrid")  # meaning and words together
```

- **Searching is free; preparing costs credits.** About **0.5 credit a page**, from the add-on's own sub-wallet (`client.credits.balance("semantic")`): a wallet that can't be spent on OCR, isn't touched by the metrics bonus, has a small daily allowance of its own (50 credits by default, set by the policy's `wallets.addons.semantic`) and can be topped up by a licence. A page with nothing to read costs nothing, a page whose text hasn't changed is never paid for twice, and nothing is embedded that can't be paid for. When the credits run out `sync` stops, keeps what it did and says so (`SearchSyncReport.paused`); the next call carries on. It never runs by itself: you decide when to spend.
- **`sync(engine=None, progress=None)`** brings the search index up to date and asks each available engine (or the one named) to prepare its pages. `progress(engine, done, total)` is called as it goes. It returns a `SearchSyncReport` per engine (`engine`, `pages`, `pending`, `credits`, `paused`, `message`). It raises `SearchUnavailableError` for a named engine that can't be used or prepared (a model that can't be downloaded, say).
- **`hybrid`** (the search engine; it has nothing to do with the `hybrid` processing tier) is a search of its own: `semantic` together with a keyword engine (`combine`, `full-text` unless told), each engine's hits shown as it found them, with the pages ranked by *reciprocal rank fusion*. A page scores the sum, over the two engines, of `1 / (60 + its position in that engine's ranking)`: only positions count, because a cosine and a BM25 can't be compared, and a page both like rises above a page only one found. It is ranked by default (`sort="rank"`). A keyword engine that can't search the query contributes nothing; `semantic` failing fails the search. Semantic search is weak where keyword search is strong (an invoice number, a name, an exact phrase) and the other way round, which is what this is for.
- `semantic` is not part of the `all` search (`in_all` is false).

### Exporting

A search result, the list of sources and the files of a source can be written to a file, as JSON or as one portable HTML page. Exporting is free and needs no add-on.

```python
result = client.search.run("invoice", engine="all")  # no limit: every match is exported
client.search.export(result, "invoice.html", "html")  # returns the path
client.search.export(result, "invoice.json")  # the saved format when none is named

client.sources.export(client.sources.list(), "sources.html", "html")
source = client.sources.list()[0]
files = client.sources.list_files(
    source.id, detailed=True
)  # with `detailed` the export shows the indexing state
client.sources.export_files(source, files, "files.json")
```

- **Format.** `json` or `html` (`vethuq.enums.ExportFormat`); left out, the saved default `client.settings.search.get/set/reset_export_format()` (`json` unless changed). A format that isn't one raises `ValueError`; so does naming a folder (`IsADirectoryError`). The folder of the file is created if needed.
- **A search export** holds the query, how the search was run (the engine, the level each normalizer ran at, the engine options, the pages an engine hadn't prepared) and every match in `result.matches`. Each match says how it was found: the engine's badge (`Exact`, `Contains`, `Relevant`, `Near`, `Word`, `Similar 83%`, `Obscured`, `Meaning`), set by the engine's add-on (`SearchEngineSpec.badge`; the label if it has none), with the score for engines that guess. `matched_by`, `modifiers` and `score` are in the JSON.
- **The HTML** is one file: logo, summary cards, the settings as chips, a row per match that opens to its text with the match highlighted, light and dark from the shared palette, printable (every row opens). Paths link to the files. Nothing is loaded from the network.
- **Languages.** Languages say which writing system they use (`LanguageSpec.script_ranges`, add-on API 0.7.0). The export lists the languages a query and its matches are written in, writes the text as is (never `\u0c24`), marks up each run in a language other than the default with `<span lang="te">` so a browser picks the right font and shaping, and sets the page's `lang` (the one language used, else the default). Every language the add-ons provide counts, usable or not: a file read when Telugu was installed is still Telugu after it is removed.
- **Filters.** In an HTML export, a table or the list of matches gets a filter bar: a dropdown of checkboxes per facet, with the number of rows each value has. Several filters narrow the list (AND), several values of one widen it (OR); a line says "Showing 3 of 5" and a button clears them. Search results filter by match type, file type, language, where the text came from (native text, OCR) and folder; sources by type and status; a source's files by type and, with `detailed=True`, status and whether they duplicate another. A filter that would split nothing (every row has the same value) is left out. The filters need JavaScript; without it the page is the plain list.
- **Any other listing.** `client.export.records(records, columns, "out.html", "html", title=..., key=...)` writes any list of dicts, and `client.export.sections([ExportSection(...), ...], "report.html", title=...)` writes several tables to one page (a summary card per table, each with its own filters). `columns` are `(field, header)` pairs; `statuses` shows a field as a colored pill, `paths` as a link to the file, `facets` as a filter, and `formats` maps a field to a function giving its cell's HTML (it must escape); `cards` adds summary cards. JSON holds the records as they are under `key` (and, for sections, a `counts` object). `ExportSection` is in `vethuq.export`. A `facets` field that isn't a column raises `ValueError`.
- **Listings.** `sources.export` shows each source's type, status, progress, languages and dates. `sources.export_files` shows each file's name, size and modification time, and, for files listed with `detailed=True`, its status, type, pages, confidence and band, low-confidence pages, languages, when it was indexed, retries, what it duplicates and why it failed. A `Source`, its id or its path names the source.

### Search settings

`client.settings.search`: `get/set/reset_engine` (`all`, `hybrid`, or an engine id; `all` unless changed), `get/set/reset_snippet_context_chars` (characters shown either side of a match; 80), `get/set/reset_export_format` (`json` or `html`; `json`), `get/set/reset_normalizer(id)` for any installed normalizer (`auto`, the default, lets each engine use its own level, or one of its levels), and `get/set/reset_case` and `get/set/reset_unicode` for the two that ship.

## GitHub runner

Run OCR in **your own GitHub account** with the free, optional GitHub add-on (`pip install "VethuQ[github]"`, or `vethuq-addon-github`). It provides the `github` [processing tier](#processing-tiers). `GitHub(client).setup()` creates a private repository you own, writes VethuQ's thin caller workflow into it and gives it a master key as a secret. `client.index.run(tier="github")` then encrypts the pages that need OCR, uploads them there, and a GitHub Actions job runs the worker image on them; results come back encrypted and are imported by `client.index.collect()` (or by the next run). Everything a job leaves in the repository (its release, tag and result artifact) is deleted once VethuQ has the result. Pages with a text layer never leave your computer. There is no template repository: GitHub copies a template whole, so the add-on writes the one workflow file itself.

```python
from vethuq.addons.github import GitHub

github = GitHub(client)
runner = github.setup("my-runner", token="github_pat_...")  # or set VETHUQ_GITHUB_TOKEN
print(runner.url, runner.workflow_ref, runner.key_fingerprint)

github.status().problems  # exists? workflow unchanged? secret set? up to date?
github.update()  # move to the newest runner version this VethuQ allows
github.versions()  # what it may set up (workflow tag, image, protocol)
github.remove(delete_repo=True)

client.tiers.get(
    "github"
).available  # True once a runner is set up and a token is in the environment
client.index.run(tier="github")  # WAITING_REMOTE while the pages are away
```

`setup(repo="vethuq-runner", *, owner=None, private=True, token=None, master_key=None, workflow_ref=None, create=True, adopt=False)`:

- **Token.** A fine-grained token limited to the runner repository: *Contents*, *Actions*, *Secrets* and *Workflows* (read and write). To create the repository (or delete it) it also needs *Administration*; otherwise create an empty repository yourself and use `create=False, adopt=True`. The token is used for the call and never stored or logged. Index runs read it from `VETHUQ_GITHUB_TOKEN` (or `GITHUB_TOKEN`); the tier is listed as unavailable, with the reason, while there is none.
- **Master key.** A random 256-bit key kept in `<data root>/github/master.key` (readable by you only) and set as the secret `VETHUQ_MASTER_KEY`. `master_key=` restores one. Without it, results of past jobs can't be read, and `status()` tells you if it is missing or isn't the one the runner has.
- **Versions.** Only the combinations of workflow tag, image and job protocol in `versions()` are ever written, because the image gets the key's effects. A repository that wasn't set up by VethuQ is refused unless `adopt=True`. Running `setup` again repairs and refreshes the runner.
- **Public repositories** are allowed (`private=False`) but show job sizes and timing and have a lower free allowance; `status()` says so. Every payload is encrypted either way.
- **Licences.** The installed add-on licences travel inside the encrypted job; the worker's add-ons check them there, so a page in a language you haven't licensed fails on its own.
- The signed policy can switch the tier off, either with the add-on's `enabled` entry or the `github_tier` feature (`GitHubUnavailableError`).

`GitHubRunner`, `GitHubStatus` and `GitHubVersion` have `to_dict()` and `to_json()`. The errors (`GitHubError` and its subclasses) and the types are in `vethuq.addons.github`. The workflow, image and protocol are described in `github/README.md` of the repository.

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

client.policy.now()  # the time notices and promotions are judged by (see below)
client.policy.notices()  # the notices active now
client.policy.section("promotions")  # a read-only view of one section of the signed policy
```

**The clock.** A notice's time window is judged by `client.policy.now()`, not by the bare local clock: it is the local clock corrected by how far it was from the policy server's `Date` header at the last fetch, and never earlier than when the cached policy was issued. Setting the computer's date back does not bring back an expired notice. It makes no request.

**Sections for other packages.** `client.policy.section(name)` returns a top-level section of the verified policy (`rate_card`, `limits`, `promotions`, ...) as read-only data, or an empty mapping when the policy has none. The entitlements package reads its limits and promotions through this and nothing else.

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

Fetching the policy exposes your IP address to its host (and nothing that identifies you). The request identifies itself only as `VethuQ-policy/1`; **your VethuQ version is not sent** (the comparison happens on your machine). Nothing else is sent, and GitHub Pages gives no access logs to us. Turn the update check off and nothing is fetched on its behalf (see [Update settings](#update-settings)).

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

The types are in `vethuq.updates`: `UpdateResult`, `FeatureAccess`, `UpgradeHelp`, `InstallKind` and the enums `UpdateStatus` and `UpdateCheckMode`.

### Upgrade help

VethuQ never upgrades itself inside the running process (file locks, virtual environments, externally-managed Pythons). `client.updates.upgrade_help()` says how it is installed and what to run:

```python
help_ = client.updates.upgrade_help(addons=["vethuq-addon-pdf"])
help_.kind  # InstallKind.VENV: INSTALLER, PIPX, VENV, EXTERNALLY_MANAGED or PIP
help_.commands  # ("python -m pip install --upgrade vethuq vethuq-addon-pdf",)
help_.steps  # the same, as sentences
```

The desktop installer build has no command: its update dialog offers **Install now**, which downloads the installer named by the signed policy, checks its size and sha256 against the policy entry, stops the background service, runs the installer silently and starts the service again.

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

It returns a `Version`:

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
| `bundles` | The bundles installed (for example `image`) |

`bundles` lists the names of the installed bundles (`vethuq-bundle-<name>` packages register under the `vethuq.bundles` entry point group). The other five of the last six are placeholders: they are empty tuples for now and will fill in as those features arrive. `to_dict()` and `to_json(indent=None)` give the same details as a dict or JSON, with these as lists.

Searching is in `vethuq.search`, processing tiers are in `vethuq.tiers`, the GitHub runner is in the GitHub add-on (`vethuq.addons.github`), credits are in `vethuq.credits`, statistics in `vethuq.stats`, metrics in `vethuq.metrics`, indexing is in `vethuq.index`, file types in `vethuq.file_types` and OCR in `vethuq.ocr`. Import `Language`, `Paths`, `Version` and `VethuQ` from `vethuq`. Everything about sources is in `vethuq.sources` (`Source`, `SourceFile`, `PurgeResult` and the enums `FileIndex` and the enums `SourceType`, `SourceStatus`, `FileStatus`, `SourceSortBy` and `SortOrder`), everything about logs is in `vethuq.logs` (`LogEntry`, `LogFile`, `Log` and its subclasses, and the enums `LogLevel`, `LogComponent` and `SortOrder`), everything about the database is in `vethuq.db`, everything about the policy is in `vethuq.policy`, everything about updates is in `vethuq.updates`, and the errors are in `vethuq.errors`. Everything else under `vethuq` is internal and may change without notice.

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
