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

Import the classes from `vethuq.errors`; everything else under `vethuq` is internal and may change without notice.
