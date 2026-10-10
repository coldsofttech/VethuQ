# VethuQ

VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

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

print(vethuq.APP_NAME)      # VethuQ
print(vethuq.APP_TAGLINE)   # Document intelligence and evidence infrastructure.
print(vethuq.APP_VERSION)   # 0.1.0

from vethuq import APP_NAME, APP_VERSION
print(f"{APP_NAME} {APP_VERSION}")
```

### Versioning

The version is not edited by hand. It comes from git tags named `vethuq-vX.Y.Z` (for example `vethuq-v0.1.0`), through hatch-vcs.

- On a tagged release, the version is exactly the tag, for example `0.1.0`.
- Commits after a tag get a development version, such as `0.1.1.dev3+g<hash>`.
- If the package isn't installed, for example when running from a source checkout, `APP_VERSION` is `0.1.0`.

## Errors

Every error VethuQ raises on purpose is a subclass of `vethuq.errors.VethuQError`. Catch that for any of them, `StartupError` for the failures that stop VethuQ from starting, `SourceError` for the source errors, `SettingsError` for the settings errors, or a specific subclass for one failure.

| Error | Exit code | Category | Raised when |
|---|---|---|---|
| `VethuQError` | 1 | Base class | Root of all the errors below |
| `StartupError` | 1 | Base class | Root of the startup failures below |
| `InvalidConfigError` | 10 | Startup | The saved settings file or the `VETHUQ_HOME` setting can't be used |
| `DataFolderNotWritableError` | 11 | Startup | VethuQ can't create or write to its data folder |
| `SchemaVersionError` | 14 | Startup | The database's schema is newer than this build supports |
| `StaleLockError` | 15 | Startup | A lock file exists but its process is no longer running |
| `CorruptDatabaseError` | 12 | Run time | The database file is damaged or isn't a VethuQ database |
| `OcrModelMissingError` | 13 | Run time | The OCR engine or its model files aren't available |
| `LanguageUnavailableError` | 16 | Run time | A language was asked for that isn't installed, enabled or known |
| `SourceError` | 20 | Sources | Root of the source errors below |
| `SourcePathError` | 21 | Sources | A source path doesn't exist, or is neither a file nor a folder |
| `SourceAlreadyExistsError` | 22 | Sources | The path is already registered as an active source |
| `SourceNotFoundError` | 23 | Sources | No source matches the id or path (or it is removed, when only active ones are searched) |
| `SourceNotRemovedError` | 24 | Sources | The source is still active, so it can't be purged |
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
| `Paths.config_file()` | The per-user `db.json`, which stores a relocated data root |

All the methods return `pathlib.Path` objects.

```python
from vethuq import Paths

print(Paths.db_path())    # e.g. /home/you/.local/share/VethuQ/db/vethuq.db
print(Paths.logs_dir())   # e.g. /home/you/.local/share/VethuQ/logs
print(Paths.DB_NAME)      # vethuq.db
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

client = vethuq.VethuQ()                              # the default database: Paths.db_path()
client = vethuq.VethuQ(db_path="/data/vethuq.db")     # or another database file
```

`client.sources`, `client.languages` and `client.settings` are the features available so far. The database is created the first time it is used. Use the client as a context manager, or call `close()`, to release it when you are done:

```python
with vethuq.VethuQ() as client:
    client.sources.create("~/docs")
```

## Sources

A source is a file or folder you register for OCR and indexing. Folders are read recursively.

```python
import vethuq

client = vethuq.VethuQ()

source = client.sources.create("~/docs", languages=["en"])   # register it
source = client.sources.get(source.id)                        # look one up
sources = client.sources.list()                               # list them
files = client.sources.list_files(source.id)                  # the files that belong to it
source = client.sources.set_languages(source.id, ["en"])      # change its languages
source = client.sources.remove(source.id)                     # remove it
result = client.sources.purge(source.id)                      # delete it for good
```

A source is identified by its **id** (an `int`) or its **path** (a `str` or `pathlib.Path`). `~` and relative paths are resolved, so the same folder written two ways is the same source. A string of digits such as `"2024"` is a path, never an id.

### The `Source` details

| Field | Description |
|---|---|
| `path` | The absolute path (required when you create a `Source`) |
| `languages` | The languages it is read in, for example `["en"]`; `None` means the global language setting applies |
| `id` | The source's id |
| `source_type` | A `SourceType`: `FILE` or `FOLDER` |
| `status` | A `SourceStatus`: `PENDING`, `INDEXED`, `ERROR` or `REMOVED` |
| `added_at` | When it was registered (UTC, ISO 8601) |
| `last_scanned_at` | When it was last scanned, or `None` |
| `is_active` | `True` unless it has been removed |
| `removed_at` | When it was removed, or `None` |

`id`, `source_type`, `status`, `added_at`, `last_scanned_at`, `is_active` and `removed_at` are set by VethuQ, so they are `None` on a `Source` you describe yourself.

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
  "added_at": "2026-10-10T12:23:42.600727+00:00",
  "last_scanned_at": null,
  "languages": ["en"]
}
```
`languages` appears only when the source has some.

### Enums

The fixed choices are enums, exported from `vethuq`. They are strings too: `SourceStatus.PENDING == "pending"`, they print and serialise as their value, and anywhere a method takes one you may pass the plain string instead.

| Enum | Members |
|---|---|
| `SourceType` | `FILE`, `FOLDER` |
| `SourceStatus` | `PENDING`, `INDEXED`, `ERROR`, `REMOVED` |
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
described = vethuq.Source("~/docs", languages=["en"])
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
client.sources.get(1, include_removed=True)     # also finds a removed source
```
Raises `SourceNotFoundError` if nothing matches. A removed source is found only with `include_removed=True`.

### Listing sources

```python
client.sources.list()                                        # active sources, by id
client.sources.list(include_removed=True)                    # and the removed ones
client.sources.list(
    status=vethuq.SourceStatus.PENDING,
    source_type=vethuq.SourceType.FOLDER,
    language="en",
    sort_by=vethuq.SourceSortBy.PATH,
    order=vethuq.SortOrder.DESC,
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

### Changing the languages

```python
client.sources.set_languages(1, ["en"])    # read in English
client.sources.set_languages(1, None)      # back to the global language setting ([] works too)
```
It returns the updated `Source` and affects files indexed from then on. It works on active sources only (a removed one raises `SourceNotFoundError`), and an unknown language raises `LanguageUnavailableError` and changes nothing.

### Removing and purging

Removing a source is reversible; purging is not.

```python
removed = client.sources.remove(1)          # kept, but marked REMOVED and no longer active
client.sources.create("~/docs")             # registering it again brings it back

result = client.sources.purge(1)            # permanently deleted
print(result.to_json())                     # {"id": 1, "path": "/home/you/docs", "type": "folder"}
```

- `remove` works on active sources and returns the removed `Source`. Removing one that is already removed raises `SourceNotFoundError`.
- `purge` works only on removed sources and returns a `PurgeResult` (`id`, `path`, `source_type`, with `to_dict()` and `to_json()`). An active source raises `SourceNotRemovedError`; an unknown one raises `SourceNotFoundError`. A purged source's language choices go with it.
- `purge_expired()` purges every source that has been removed for longer than the retention, and returns the list of `PurgeResult`s. The retention is 7 days unless you change it in the [settings](#settings). Pass `retention_minutes=` to use another value for one call.

```python
client.sources.purge_expired()                       # uses the setting (7 days by default)
client.sources.purge_expired(retention_minutes=60)   # removed more than an hour ago
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
    print(error)    # Unknown language 'xx'. Available languages: en.
```

A plain string such as `"en,te"` isn't accepted; pass a list.

### Source errors

| Raised | When |
|---|---|
| `SourcePathError` | The path doesn't exist (or, for `list_files`, is no longer on disk), or is neither a file nor a folder |
| `SourceAlreadyExistsError` | The path is already an active source, or the `Source` given was already created |
| `SourceNotFoundError` | No source matches the id or path |
| `SourceNotRemovedError` | `purge` was called on a source that is still active |
| `LanguageUnavailableError` | A language isn't one VethuQ knows |

All of them are `VethuQError`s; the first four are also `SourceError`s.

## Languages

`client.languages` lists the languages VethuQ can read documents in. English (`en`) is there from the start.

```python
import vethuq

client = vethuq.VethuQ()

for language in client.languages.list_all():
    print(language.id, language.language)
# 1 en
```

`list_all()` returns a list of `Language` objects, in VethuQ's language order (English first).

| Field | Description |
|---|---|
| `id` | The language's id in the database |
| `language` | The language id you use when you create a source, for example `"en"` |

Like `Source`, a `Language` has `to_dict()` and `to_json(indent=None)`:

```python
language = client.languages.list_all()[0]
language.to_dict()        # {"id": 1, "language": "en"}
language.to_json()        # '{"id": 1, "language": "en"}'
```

Any id in this list can be used as `languages=[...]` when you create a source. Any other id raises `LanguageUnavailableError`.

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
client.settings.sources.get_removed_retention_minutes()          # 10080
client.settings.sources.set_removed_retention_minutes(24 * 60)   # keep for one day
client.settings.sources.reset_removed_retention_minutes()
```

A value that isn't a whole number of 0 or more raises `vethuq.errors.InvalidSettingValueError`, and the setting is left as it was. Settings are saved in the database, so every client using that database sees the same values.

Import `Language`, `Paths`, `PurgeResult`, `Source`, `SourceFile`, `VethuQ` and the enums (`SourceType`, `SourceStatus`, `SortOrder`, `SourceSortBy`) from `vethuq`, and the errors from `vethuq.errors`; everything else under `vethuq` is internal and may change without notice.
