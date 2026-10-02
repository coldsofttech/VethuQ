# Python API reference

Install with `pip install vethuq` (Windows or Linux, Python 3.11+) — this
also gives you the `vethuq` CLI, see [docs/CLI.md](CLI.md).

```python
import vethuq

client = vethuq.Vethuq()
```

`vethuq` is a thin public surface over the same engine that powers the
CLI and desktop app: registering sources (files/folders for OCR and
indexing) and running/controlling indexing. It grows as more of VethuQ's
functionality (search) is exposed here.

Every method below connects to VethuQ's local SQLite database — the same
one the CLI and desktop app use, at `DB_PATH` — for the single call and
closes it again. There's no connection object to manage.

## `client.db`

### `integrity_check()`

Check the database for corruption now and return an `IntegrityCheckResult` with `ok` (`bool`) and `errors` (the problems SQLite reported, empty when `ok`). The outcome is also logged.

```python
result = client.db.integrity_check()
if not result.ok:
    print(result.errors)
```

## `client.index`

Indexing runs in the background, the same way as `vethuq index run`. See
[docs/CLI.md](CLI.md) for the underlying concepts (targets, pause/resume,
history).

### `history(target=None, limit=10)`

Return the last `limit` background index runs (`IndexRun`), most recent
first, optionally filtered to one source. A run over all sources is
included alongside runs targeted at just `target`. Raises
`SourceNotFoundError` if `target` doesn't match a registered source.

### `pause()` / `resume()`

Pause or resume the currently running background index. Raises
`IndexRunnerError` if no run is currently active.

### `restart(target=None, *, force=False, wait=False)`

Retry only previously-failed files, in the background. Same arguments and
return value as `run`.

### `run(target=None, *, force=False, wait=False)`

Start OCR indexing on registered sources. `target` is a source id or path;
omit it to index every pending source. Returns the background process id,
or, with `wait=True`, blocks until the run finishes and returns its final
`IndexState` instead.

Raises `AlreadyRunningError` if a run is already in progress, and
`StaleLockError` if a previous run left a stale lock (`force=True` clears
it). Raises `SourceNotFoundError` if `target` doesn't match a registered
source.

```python
pid = client.index.run()
state = client.index.run(wait=True)
```

### `status(target=None)`

With no `target`, returns the live/last-known `IndexState` (or `None` if no
run has ever started). With a `target` (source id or path), returns a
`DocumentResult` per file indexed under that source instead. Raises
`SourceNotFoundError` if `target` doesn't match a registered source.

```python
state = client.index.status()
print(state.status, state.processed_files, state.total_files)

for result in client.index.status(source.id):
    print(result.file_path, result.status)
```

### `stop()`

Stop the currently running background index and wait for confirmation.
Raises `IndexRunnerError` if no run is currently active.

## `client.logs`

Read VethuQ's log files — mirrors `vethuq logs` in the CLI.

### `tail(component, lines=40, *, level=None, day=None)`

The most recent `lines` entries of a component's log, oldest first, as a list
of strings. `component` is one of `LOG_COMPONENTS` (`"database"`, `"index"`,
`"ui"`, `"cli"`). `level` keeps only entries at or above it (one of
`LOG_LEVEL_VALUES`); `day` is a `datetime.date` for a past day's log instead of
today's. Raises `LogNotFoundError` if there is no log for that day, and
`ValueError` for an unknown component or level.

```python
for entry in client.logs.tail("index", 40, level="warning"):
    print(entry)
```

## `client.search`

Search previously OCR-indexed content — mirrors `vethuq search` in the CLI.

### `export(matches, query, output, format_=None)`

Write `matches` for `query` to `output` (a path) as JSON or HTML, and
return the resolved `Path`. `format_` defaults to
`client.settings.search.export_format` if not given, and must be one of
`SEARCH_EXPORT_FORMATS`.

```python
matches = client.search.run("invoice")
client.search.export(matches, "invoice", "results.html", "html")
```

### `run(content, *, context_chars=None)`

Search indexed OCR text for `content`, case-insensitively. Returns one
`SearchMatch` per matching page, ordered by file path (pages of the same
PDF stay in page order). Only successfully indexed documents are
considered. `context_chars` defaults to `client.settings.search.snippet`
if not given.

```python
for match in client.search.run("invoice"):
    print(match.file_path, match.matched)
```

## `client.settings`

Mirrors `vethuq settings ...` in the CLI — see [docs/CLI.md](CLI.md).

### `client.settings.db.integrity_check`

- `get()` — whether the database integrity check runs when the database is opened (`"auto"` by default)
- `set(value)` — `value` must be one of `INTEGRITY_CHECK_VALUES` (`"enable"`, `"disable"`, `"auto"`); raises `InvalidSettingValueError` otherwise
- `get_interval_minutes()` — minutes between automatic checks when `"auto"` (1 day by default)
- `set_interval_minutes(minutes)` — raises `InvalidSettingValueError` if `minutes` is negative

### `client.settings.gpu`

- `is_enabled()` — whether OCR should attempt to use the GPU (disabled by default)
- `enable()` / `disable()`

### `client.settings.index.engine`

- `get()` — how thoroughly OCR looks for rotated text (`"quick"` by default)
- `set(value)` — `value` must be one of `OCR_ENGINE_MODES` (`"quick"`, `"moderate"`,
  `"deep"`); raises `InvalidSettingValueError` otherwise. Files are always indexed
  quick first; moderate (90/180/270°) and deep (every 15°) then run in the background.

### `client.settings.index.ocr_retry`

- `get()` — times a file's OCR is retried after a transient failure (3 by default)
- `set(attempts)` — raises `InvalidSettingValueError` if `attempts` is negative

### `client.settings.index.removed_retention`

- `get()` — minutes a removed source is kept before it's purged (7 days by default)
- `set(minutes)` — raises `InvalidSettingValueError` if `minutes` is negative

### `client.settings.index.stale_lock`

- `get()` — whether a stale lock auto-clears on the next run (`"auto"` by default)
- `set(value)` — `value` must be one of `STALE_LOCK_VALUES`
  (`"enable"`, `"disable"`, `"auto"`); raises `InvalidSettingValueError` otherwise

### `client.settings.index.thread_workers`

- `get()` — worker threads background indexing uses (`"0"`, disabled, by default)
- `set(value)` — `value` must be `"0"`-`ThreadWorkersSettings.MAX` or
  `ThreadWorkersSettings.AUTO`; raises `InvalidSettingValueError` otherwise

### `client.settings.logs.level`

- `get()` — the log level (`"info"` by default)
- `set(value)` — `value` must be one of `LOG_LEVEL_VALUES` (`"debug"`, `"info"`,
  `"warning"`, `"error"`); raises `InvalidSettingValueError` otherwise

### `client.settings.logs.retention`

- `get()` — days of daily log files kept (`15` by default)
- `set(days)` — `days` must be at least 1; raises `InvalidSettingValueError` otherwise

### `client.settings.search.export_format`

- `get()` — default format `search --export` writes to (`"json"` by default)
- `set(format_)` — `format_` must be one of `SEARCH_EXPORT_FORMATS`
  (`"json"`, `"html"`); raises `InvalidSettingValueError` otherwise

### `client.settings.search.snippet`

- `get()` — characters of context `search` shows around a match (80 by default)
- `set(chars)` — raises `InvalidSettingValueError` if `chars` is negative

```python
client.settings.gpu.enable()
client.settings.search.snippet.set(120)
client.settings.index.thread_workers.set(ThreadWorkersSettings.AUTO)
```

## `client.sources`

### `add(path)`

Register a file or folder as a source. Folders are indexed recursively.
Raises `SourcePathError` if `path` doesn't exist, `SourceAlreadyExistsError`
if it's already registered.

```python
source = client.sources.add("./path/to/folder-or-file")
```

### `list(include_inactive=False)`

Return registered sources, most recently added first.

```python
for source in client.sources.list():
    print(source.id, source.path)
```

### `remove(source_id)`

Unregister a source by id or path. Raises `SourceNotFoundError` if it
doesn't exist.

## `client.stats`

Accumulated OCR processing/confidence statistics — mirrors `vethuq stats ...`
in the CLI.

### `confidence()`

Return per-(file type, process type) running averages (`ConfidenceMetric`):
page count and average confidence.

### `processing()`

Return per-(phase, file type, size) running averages (`ProcessingMetric`):
document count, average duration, peak memory, and CPU use. `phase` is 1 (quick),
2 (moderate) or 3 (deep) — each phase keeps its own averages.

### `reset()`

Clear both. They're running averages folded in as OCR completes, and
`client.index.run`'s ETA estimate is based on them — after a reset, ETAs are
unavailable again until enough files have been (re)indexed to rebuild them.

```python
for m in client.stats.processing():
    print(m.file_type, m.size_bucket, m.avg_duration_seconds)

client.stats.reset()
```

## `DB_PATH`

The `Path` to VethuQ's local SQLite database (the same one the CLI and
desktop app use).

## `ConfidenceMetric`

- `file_type`, `process_type`, `page_count`, `avg_confidence`, `updated_at`

## `DocumentResult`

One indexed file's result under a source, returned by `index.status(target)`:

- `file_path`, `status`, `error_message`
- `confidence` (`None` until successfully indexed)
- `started_at`, `completed_at`, `duration` (seconds; `None` while pending)
- `duplicate_of_path` (set if this file's content matched an already-indexed
  file)

## `IndexRun`

One past run's summary, returned by `index.history`:

- `id`, `target`, `mode`, `status`, `pid`
- `total_files`, `processed_files`, `failed_files`, `workers`
- `started_at`, `completed_at`

## `IndexState`

A background run's live/last-known progress, returned by `index.run`/
`index.restart` (with `wait=True`) and `index.status()` (with no `target`):

- `run_id`, `pid`, `target`, `mode` (`"run"` or `"restart"`)
- `status` (`"running"`, `"paused"`, `"completed"`, `"stopped"`, or `"failed"`)
- `total_files`, `processed_files`, `failed_files`
- `thread_workers_setting`, `workers` (current effective worker count)
- `current_files` (files being processed right now)
- `started_at`, `updated_at`

## `IntegrityCheckResult`

The outcome of a database integrity check, returned by `client.db.integrity_check`:

- `ok` (`True` when the database is intact)
- `errors` (the problems SQLite reported; empty when `ok`)

## `ProcessingMetric`

- `phase`, `file_type`, `size_bucket`, `document_count`
- `avg_duration_seconds`, `avg_peak_memory_mb`, `avg_cpu_percent`
- `updated_at`

## `SearchMatch`

One matching page, returned by `client.search.run`:

- `file_id`, `file_name`, `file_path`
- `page_number`, `total_pages` (both `None` for a non-paginated file, e.g. an image)
- `before`, `matched`, `after` (the match split out for highlighting)
- `truncated_before`, `truncated_after`
- `duplicate_of_path` (set if this file's content matched an already-indexed file)

## `Source`

The registered-source model returned by `sources.add`/`sources.list`/
`sources.remove`:

- `id`, `path`, `source_type` (`"file"` or `"folder"`)
- `status` (`"pending"`, `"indexed"`, `"error"`, or `"removed"`)
- `added_at`, `last_scanned_at`
- `is_active`, `removed_at`

## Errors

`SourceError` is the base class for `SourceAlreadyExistsError`,
`SourceNotFoundError`, and `SourcePathError` — catch `SourceError` to
handle any of them generically, or a specific subclass to handle one case.

`IndexRunnerError` is the base class for `AlreadyRunningError` and
`StaleLockError`, raised by the indexing methods above.

`SettingsError` is the base class for `InvalidSettingValueError`, raised by
the `set(...)` methods under `client.settings` when given an invalid value
(it's also a `ValueError`, so existing `except ValueError` handling still
works).
