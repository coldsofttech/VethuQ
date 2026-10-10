# vethuq-addon-api

The contract between VethuQ and its add-ons. It has no dependencies and holds no behaviour: the
`Addon` base class, the `Hook` points, the `Host` VethuQ offers, and a `FakeHost` to test an add-on
without VethuQ.

Add-ons are separate packages (for example `vethuq-addon-backup`). They register an `Addon` subclass
under the `vethuq.addons` entry-point group; VethuQ finds installed add-ons by that group, and
`from vethuq.addons.<id> import ...` reaches the add-on's public classes.

```python
from vethuq_addon_api import Addon, Manifest, MigrationInfo


class BackupAddon(Addon):
    manifest = Manifest(id="backup", name="vethuq-addon-backup", version="0.1.0")

    def on_open(self) -> None: ...
    def before_migration(self, info: MigrationInfo) -> None: ...
```

```toml
[project.entry-points."vethuq.addons"]
backup = "vethuq_addon_backup:BackupAddon"
```

## Language add-ons

An add-on can provide languages. Override `languages()` and return `LanguageSpec`s:

```python
def languages(self) -> list[LanguageSpec]:
    return [LanguageSpec(id="en", label="English", script="latin", default=True)]
```

`default=True` marks the system default language (every install has exactly one). A language that
exists but can't be used right now (a lapsed licence) is returned with `available=False` and a `reason`.

## Rules

- Hooks are best effort. VethuQ logs a failing hook and carries on.
- An add-on checks its own licence. VethuQ never tells it that a licence is valid.
- The API version is `major.minor.patch`, the same form as the policy's `compatibility.addon_api`. An add-on declares the range it works with; an add-on outside the
  range is listed as incompatible and not run.

## Testing an add-on

```python
from vethuq_addon_api.testing import FakeHost

host = FakeHost(tmp_path / "vethuq.db")
addon = BackupAddon(host)
addon.on_open()
```
