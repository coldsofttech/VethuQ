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

`default=True` marks the system default language (every install has exactly one). `script_ranges` are the code point ranges of its writing system, so VethuQ can recognise text in it (exports tag such runs with the language). A language that
exists but can't be used right now (a lapsed licence) is returned with `available=False` and a `reason`.

## File types, OCR engines and phases

- `file_types()` returns `FileTypeSpec`s: an id, the extensions, and a `DocumentReader` that yields
  each page's native text, its large image regions and a way to render it.
- `ocr_engines()` returns `OcrEngineProvider`s: they build an `OcrEngine` for a language and a model
  profile, and say which models that needs, where they are kept and how to download them. VethuQ
  passes the folder to keep models in.
- `processing_tiers()` returns `TierSpec`s: an id, the credit wallet its work is paid from, and an
  `OcrExecutor` that reads images somewhere (`recognize` for a synchronous executor; `submit`,
  `poll`, `collect` and `cancel` for one whose batches finish later).
- `ocr_phases()` returns `OcrPhaseSpec`s: an order, the angles to read and the model profile.
- `normalizers()` returns `Normalizer`s (search): what counts as "the same character" (`case`,
  `unicode`). A normalizer has levels (one of them the identity), an `order`, a `version`, `fold`
  (text to normalized text, remembering where each character came from: `Folded`) and
  `index_form` (the coarsest form, which VethuQ's search index records).
- `search_engines()` returns `SearchEngineSpec`s (search): an id, a `SearchEngine` and the
  normalizers it uses (`NormalizerUse`: default level, fixed, whether the saved setting reaches
  it; `optional` when the engine works without that normalizer installed). `engine.search(request,
  corpus)` yields `Hit`s; `request.pipeline` folds the query and each page alike,
  `corpus.candidates(query)` gives the pages that can match (`candidates(None)` gives all of them:
  an engine that tolerates typos can't be narrowed by the query).
- An engine can declare options a search may override (`SearchOption`; they arrive in
  `request.options`), give it a short `badge` ("Exact", "Similar") that exports show beside a hit, say it is `approximate` (it guesses, so VethuQ's ranking puts it below the
  engines that match the text), and prepare pages ahead of searches by overriding
  `SearchEngine.pending(corpus)` and `SearchEngine.sync(corpus, progress)` (`SyncReport`): searching
  never prepares anything. VethuQ does the ranking, the merging of hits several engines agree on and
  the `hybrid` fusion; an engine only reports its hits.

## Commands and settings

`Addon.cli()` returns a `CliGroup`: commands (`CliCommand`, with typed `CliParam`s), nested groups and
settings (`CliSetting`: `get(client)` and `set(client, value)` work in text; `reset` is optional;
`choices` limits the values). No CLI library is involved. VethuQ mounts the group as
`vethuq <group name> ...` and the settings under `vethuq settings addons <group name> ...`; the
interactive shell and the desktop Settings screen are built from the same description, so an add-on
writes nothing for them. Store a setting with `Host.set_setting`: it is kept in VethuQ's database as
`addon.<id>.<key>`, so a backup holds it, a restore brings it back and a reset leaves the default.

- A command returns a `CliResult` (`lines`, a `table`, `data` for `--json`, `ok=False` for exit status 1),
  a string, or nothing.
- A licensed add-on that is not licensed still loads: `get` or `set` may raise with the reason (for
  example "needs a licence"); the CLI shows it as `Unavailable: <reason>` and the Settings screen shows
  the setting read-only with that note.
- An add-on that is installed but not running (turned off, built for another Python or platform,
  or failing to load) cannot describe its commands. VethuQ mounts a stand-in `vethuq <add-on id>`
  and a row in the add-on settings that say why it is not running and what to do.
- `licence_commands(Docx, "Word (.docx)")` gives the shared `licence show|set|remove` group.

## What the host gives an add-on

`Host` (see `Addon.host`): its settings (`get_setting`, `set_setting`), `data_dir()` (a folder of its
own for files that don't belong in VethuQ's database), `credits` (`rate`, `balance_milli`, `charge`:
the add-on's own credit sub-wallet, for work that costs compute; `CreditsExhaustedError` when it
runs out) and the licences and policy switches described above.

The reader and engine types are in this package, so an add-on and VethuQ share them; the heavy
libraries stay inside the add-ons.

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
