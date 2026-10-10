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

Every error VethuQ raises on purpose is a subclass of `vethuq.errors.VethuQError`. Catch that for any of them, `StartupError` for the failures that stop VethuQ from starting, `SourceError` for the source errors, or a specific subclass for one failure.

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

The database is created the first time it is used. Use the client as a context manager, or call `close()`, to release it when you are done:

```python
with vethuq.VethuQ() as client:
    client.sources.create("~/docs")
```

## Sources

A source is a file or folder you register for OCR and indexing. Folders are read recursively.

### Creating a source

`client.sources.create()` registers a source and returns its details as a `Source`.

```python
import vethuq

client = vethuq.VethuQ()

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

- The path can be a `str` or a `pathlib.Path`. `~` and relative paths are resolved, so the same folder written two ways is the same source.
- `languages` is a list of language ids. Give it on the call or on the `Source`, not both.
- Re-creating a source that was removed brings it back, reset to `pending`.
- The `Source` you pass in is left untouched; `create` returns a new, filled-in one. A `Source` that was already created can't be passed again.

### The `Source` details

| Field | Description |
|---|---|
| `path` | The absolute path (required when you create a `Source`) |
| `languages` | The languages it is read in, for example `["en"]`; `None` means the global language setting applies |
| `id` | The source's id |
| `source_type` | `"file"` or `"folder"` |
| `status` | `"pending"`, `"indexed"`, `"error"` or `"removed"` |
| `added_at` | When it was registered (UTC, ISO 8601) |
| `last_scanned_at` | When it was last scanned, or `None` |
| `is_active` | `True` unless it has been removed |
| `removed_at` | When it was removed, or `None` |

`id`, `source_type`, `status`, `added_at`, `last_scanned_at`, `is_active` and `removed_at` are set by VethuQ, so they are `None` on a `Source` you describe yourself.

### As JSON

```python
source = client.sources.create("~/docs", languages=["en"])

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

### Languages

VethuQ keeps a list of the languages it can read. English (`en`) is there from the start, and others are added as they become available. A source stores the languages it is read in, and a source with none uses the global language setting.

- Language ids are case-insensitive and may be repeated; `["EN", "en"]` is stored as `["en"]`.
- Languages are always returned in VethuQ's own language order, not the order you gave them.
- A language VethuQ doesn't know raises `vethuq.errors.LanguageUnavailableError`, and nothing is created. The hint lists the available languages, and every unknown id is reported at once:

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
| `SourcePathError` | The path doesn't exist, or is neither a file nor a folder |
| `SourceAlreadyExistsError` | The path is already an active source, or the `Source` given was already created |
| `LanguageUnavailableError` | A language isn't one VethuQ knows |

All of them are `VethuQError`s; the first two are also `SourceError`s.

Import `Paths`, `Source` and `VethuQ` from `vethuq` and the errors from `vethuq.errors`; everything else under `vethuq` is internal and may change without notice.
