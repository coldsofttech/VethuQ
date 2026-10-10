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

Every error VethuQ raises on purpose is a subclass of `vethuq.errors.VethuQError`. Catch that for any of them, `StartupError` for the failures that stop VethuQ from starting, or a specific subclass for one failure.

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
| `LanguageUnavailableError` | 16 | Run time | An OCR language was asked for that isn't installed, enabled or known |

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

`vethuq.paths.Paths` reports where VethuQ keeps its data. It is read-only: it returns paths and creates nothing on disk.

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
import vethuq

print(vethuq.paths.Paths.db_path())    # e.g. /home/you/.local/share/VethuQ/db/vethuq.db
print(vethuq.paths.Paths.logs_dir())   # e.g. /home/you/.local/share/VethuQ/logs
print(vethuq.paths.Paths.DB_NAME)      # vethuq.db
```

### Where the data root comes from

The data root is chosen in this order:

1. The `VETHUQ_HOME` environment variable, if set.
2. The location saved in the per-user `db.json`.
3. The platform default (for example `%APPDATA%\VethuQ` on Windows, `~/.local/share/VethuQ` on Linux).

The backups folder is `<data root>/db/backups` unless a different one is saved in `db.json`.

Import the classes from `vethuq.errors` and `vethuq.paths`; everything else under `vethuq` is internal and may change without notice.
