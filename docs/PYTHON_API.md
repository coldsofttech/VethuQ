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

### Backup, restore, reset and repair

- `backup_create(name=None)` — take a compressed backup now and return a `BackupInfo` (`name`, `path`, `size`, `created_at`, `kind` of `"auto"`, `"safety"` or `"manual"`); raises `BackupError` for a bad or taken name, or if the database fails its integrity check
- `backup_list()` — every backup, newest first
- `backup_delete(name)` — raises `BackupError` if there is no such backup
- `restore(name_or_path)` — replace the database with a backup; returns the `"safety"` backup of what it replaced
- `reset()` — delete the database and all its data; returns the `"safety"` backup
- `repair()` — rebuild the indexes and return a fresh `IntegrityCheckResult`

`restore`, `reset` and `repair` raise `IndexRunnerError` while an index run is active.

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

### `reindex(target, *, force=False, wait=False)`

Re-index every file under a source, not just failed ones, updating existing
documents in place. Same errors and return value as `run`.

### `reindex_file(file, *, source=None, force=False, wait=False)`

Re-index one file by document id or path. Raises `FileNotTrackedError` if it
isn't tracked and `AmbiguousFileError` if it sits under several sources and
`source` isn't given.

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

### `export(matches, query, output, format_=None, *, engine=None, case_sensitive=False, threshold=None, distance=None)`

Write `matches` for `query` to `output` (a path) as JSON or HTML, and
return the resolved `Path`. `format_` defaults to
`client.settings.search.export_format` if not given, and must be one of
`SEARCH_EXPORT_FORMATS`. Pass the `engine`, `case_sensitive` and (for
`fuzzy` or `proximity`) `threshold` or `distance` the search
ran with to record them in the file.

```python
matches = client.search.run("invoice")
client.search.export(matches, "invoice", "results.html", "html")
```

### `run(content, *, context_chars=None, engine=None, case_sensitive=None, threshold=None, distance=None)`

Search indexed OCR text for `content`. Returns one `SearchMatch` per
occurrence, ordered by file path (pages of the same PDF stay in page
order, occurrences within a page in text order) — or best match first for
the `full-text`, `fuzzy` and `proximity` engines. Only successfully indexed documents are
considered. `context_chars` defaults to `client.settings.search.snippet`
if not given.

With the default `engine="all"` every engine runs and the hits come back in
ranked page order — strictest match first (see `run_pages`) — each `SearchMatch`
labelled with the engine that found it (`engine`) and every engine that did
(`matched_by`); the options below then reach the engines that can use them and
are never rejected.

`engine` is one of `SEARCH_ENGINES` and defaults to
`client.settings.search.engine`:

- `"all"` — every engine at once, the pages ranked together (the default)
- `"like"` — `content` anywhere, even inside a word, ignoring case
- `"exact"` — `content` as typed: same case, as a whole word
- `"full-text"` — pages containing `content`'s words (any case, English word
  forms; `"quote a phrase"`, end a word with `*` for a prefix), ranked by
  relevance (`SearchMatch.score`)
- `"fuzzy"` — words *close to* `content`'s, tolerating typos and OCR misreads
  (`Muzeum`, `Museurn` for `Museum`), closest first. Every word must be matched;
  words under 4 letters and words containing a digit must match exactly.
  `SearchMatch.score` is the found word's similarity, 0–1 (1.0 = identical)
- `"proximity"` — passages where all of `content`'s terms (at least two words or
  `"quoted phrases"`, in any order) sit within `distance` words of each other, one
  `SearchMatch` per passage spanning its first to its last term, on pages ranked by
  relevance (`SearchMatch.score`)

`case_sensitive` defaults to `client.settings.search.case_sensitive`, and
only `"like"` and `"fuzzy"` act on it (`"exact"` is always case-sensitive,
`"full-text"` and `"proximity"` never are; for `"fuzzy"` a difference in case
counts as one edit). `threshold` (`"fuzzy"` only) is the minimum similarity between
`content`'s words and the words found — `1 − edits ÷ length of the longer
word`, at most 2 edits: a name from `SEARCH_FUZZY_PRESETS` (`"strict"` 90%,
`"balanced"` 80%, `"loose"` 65%), a percentage (`"80%"`) or a number above 0 and up
to 1, defaulting to `client.settings.search.fuzzy.threshold`. `distance`
(`"proximity"` only) is the most words between a passage's first and last term — other
terms in between count: a name from `SEARCH_PROXIMITY_PRESETS` (`"tight"` 3, `"medium"`
10, `"loose"` 30) or a number from 1 to `SEARCH_PROXIMITY_MAX_DISTANCE`, defaulting to
`client.settings.search.proximity.distance`. Raises `SearchOptionError` (a
`ValueError`; its `option` says which argument) for an unknown engine, an invalid
`threshold` or `distance`, or an explicit `case_sensitive`, `threshold` or `distance`
the engine can't honour, and `SearchQueryError` (also a `ValueError`) for a `"proximity"`
query of fewer than two terms.

```python
for match in client.search.run("invoice"):
    print(match.file_path, match.matched)
```

### `run_pages(content, *, context_chars=None, case_sensitive=None, threshold=None, distance=None)`

Search with every engine at once and return the pages found, best first, as
`PageResult`s. Pages are ranked by the strictest engine that found them —
`"exact"` (Exact), `"like"` (Contains), `"proximity"` (Near), `"full-text"` (Word),
`"fuzzy"` (Similar), in that order (`ENGINE_TIERS`; `ENGINE_BADGES` maps each to the
label the CLI and the UI show) — and within a tier by that engine's own signal, so
a page is one result however many engines found it. `case_sensitive`, `threshold`
and `distance` default to their settings and reach only the engines that can use
them; `proximity` is skipped for a query of fewer than two terms.

```python
for page in client.search.run_pages("Museum"):
    print(page.file_path, page.page_number, vethuq.hit_badge(page.hits[0]))
    for hit in page.hits:  # best first
        print("  ", vethuq.hit_badge(hit), hit.matched)
```

Examples, assuming a page that reads "Learn English at the English Institute"
(the same ones as in [docs/CLI.md](CLI.md)):

**`"like"`** (the default) finds the text anywhere, even inside a word:

```python
client.search.run("eng")  # case-insensitive: finds "English" (twice)
client.search.run("english", engine="like")  # case-insensitive: finds "English"
client.search.run("English", case_sensitive=True)  # case-sensitive: finds "English"
client.search.run(
    "english", case_sensitive=True
)  # case-sensitive: no match ("english" != "English")
client.search.run("ENGLISH", case_sensitive=False)  # case-insensitive, even if the setting is on
```

**`"exact"`** finds the text as typed, as a whole word. It is always
case-sensitive, so `case_sensitive=True` is allowed but redundant, and
`case_sensitive=False` raises `SearchOptionError`:

```python
client.search.run("English", engine="exact")  # finds "English"
client.search.run("english", engine="exact")  # no match: wrong case
client.search.run("eng", engine="exact")  # no match: only part of a word
client.search.run("English Institute", engine="exact")  # finds the phrase as typed
client.search.run("English", engine="exact", case_sensitive=True)  # same as the first example
client.search.run(
    "English", engine="exact", case_sensitive=False
)  # raises SearchOptionError: always case-sensitive
```

**`"full-text"`** finds pages containing the words, in any form, best
matches first (`SearchMatch.score` is the relevance). It is always
case-insensitive, so `case_sensitive=False` is allowed but redundant, and
`case_sensitive=True` raises `SearchOptionError`:

```python
client.search.run("english", engine="full-text")  # finds "English", any case
client.search.run("ENGLISH", engine="full-text")  # same results
client.search.run("eng*", engine="full-text")  # prefix: finds "English", "engine", "engineering"...
client.search.run("eng", engine="full-text")  # no match: not a whole word
client.search.run("english institute", engine="full-text")  # both words on the page, any order
client.search.run(
    '"english institute"', engine="full-text"
)  # the exact phrase, words adjacent and in order
client.search.run("english", engine="full-text", case_sensitive=False)  # same as the first example
client.search.run(
    "english", engine="full-text", case_sensitive=True
)  # raises SearchOptionError: always case-insensitive
```

**`"fuzzy"`** finds words close to yours, closest first
(`SearchMatch.score` is each word's similarity):

```python
client.search.run("Museum", engine="fuzzy")  # finds "Muzeum", "Musuem", "Museums"
client.search.run("Museum", engine="fuzzy", threshold="loose")  # also "Museurn"
client.search.run("Museum", engine="fuzzy", threshold="70%")  # a percentage instead of a name
client.search.run(
    "museum", engine="fuzzy", case_sensitive=True
)  # a difference in case counts as one edit
client.search.run(
    "Museum", engine="like", threshold=0.7
)  # raises SearchOptionError: only fuzzy has a threshold
```

**`"proximity"`** finds passages where all your words sit close together, one
`SearchMatch` per passage:

```python
client.search.run("payment termination", engine="proximity")  # within 10 words
client.search.run("payment termination", engine="proximity", distance="loose")  # 30 words
client.search.run("late fee", engine="proximity", distance=5)
client.search.run("payment", engine="proximity")  # raises SearchQueryError: needs two terms
```

## `client.settings`

Mirrors `vethuq settings ...` in the CLI — see [docs/CLI.md](CLI.md).

### `client.settings.db.integrity_check`

- `get()` — whether the database integrity check runs when the database is opened (`"auto"` by default)
- `set(value)` — `value` must be one of `INTEGRITY_CHECK_VALUES` (`"enable"`, `"disable"`, `"auto"`); raises `InvalidSettingValueError` otherwise
- `get_interval_minutes()` — minutes between automatic checks when `"auto"` (1 day by default)
- `set_interval_minutes(minutes)` — raises `InvalidSettingValueError` if `minutes` is negative

### `client.settings.db.backup`

- `get()` / `set(value)` — automatic backups, one of `BACKUP_VALUES` (`"enable"` by default, `"disable"`)
- `get_interval_minutes()` / `set_interval_minutes(minutes)` — minutes between automatic backups (1 day by default, at least 1)
- `get_retention_days()` / `set_retention_days(days)` — days automatic backups are kept (7 by default, at least 1)

Invalid values raise `InvalidSettingValueError`.

### `client.settings.gpu`

- `is_enabled()` — whether OCR should attempt to use the GPU (disabled by default)
- `enable()` / `disable()`

### `client.settings.index.removed_retention`

- `get()` — minutes a removed source is kept before it's purged (7 days by default)
- `set(minutes)` — raises `InvalidSettingValueError` if `minutes` is negative

### `client.settings.index.stability_check`

- `get()` — seconds a file must stay unchanged, across two checks, before it's indexed (`1.0` by default; `0` disables the check)
- `set(seconds)` — raises `InvalidSettingValueError` if `seconds` is negative

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

### `client.settings.ocr.engine`

- `get()` — how thoroughly OCR looks for rotated text (`"quick"` by default)
- `set(value)` — `value` must be one of `OCR_ENGINE_MODES` (`"quick"`, `"moderate"`,
  `"deep"`); raises `InvalidSettingValueError` otherwise. Files are always indexed
  quick first; moderate (90/180/270°) and deep (every 15°) then run in the background.

### `client.settings.ocr.retry`

- `get()` — times a file's OCR is retried after a transient failure (3 by default)
- `set(attempts)` — raises `InvalidSettingValueError` if `attempts` is negative

### `client.settings.search.case_sensitive`

- `get()` — whether `search` matches case by default (`False` by default; only
  the `like` engine acts on it)
- `set(enabled)`

### `client.settings.search.engine`

- `get()` — default engine `search` uses (`"all"` by default: every engine, ranked together)
- `set(engine)` — `engine` must be one of `SEARCH_ENGINES` (`"all"`, `"like"`, `"exact"`,
  `"full-text"`, `"fuzzy"`, `"proximity"`); raises `InvalidSettingValueError` otherwise

### `client.settings.search.fuzzy.threshold`

- `get()` — the stored default threshold for the `fuzzy` engine, as set: a name from
  `SEARCH_FUZZY_PRESETS`, or a percentage or similarity as text (`"balanced"` by default)
- `set(threshold)` — a name from `SEARCH_FUZZY_PRESETS` (`"strict"` 90%, `"balanced"`
  80%, `"loose"` 65%), a percentage (`"75%"`, or a whole number such as `75`) or a
  similarity above 0 and up to 1 (`0.75`); raises `InvalidSettingValueError` otherwise

### `client.settings.search.proximity.distance`

- `get()` — the stored default distance for the `proximity` engine, as set: a name from
  `SEARCH_PROXIMITY_PRESETS` or a number of words as text (`"medium"`, 10 words, by default)
- `set(distance)` — a name from `SEARCH_PROXIMITY_PRESETS` (`"tight"` 3 words, `"medium"`
  10, `"loose"` 30) or a number of words from 1 to `SEARCH_PROXIMITY_MAX_DISTANCE`;
  raises `InvalidSettingValueError` otherwise

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

### `files(path_or_id)`

Return the files tracked under a source (by id or path), ordered by file
path, as `SourceFile` objects. Raises `SourceNotFoundError` if no active
source matches.

```python
for file in client.sources.files(3):
    print(file.id, file.file_path, file.status)
```

### `remove(source_id)`

Unregister a source by id or path. Raises `SourceNotFoundError` if it
doesn't exist.

### `purge(path_or_id)`

Permanently delete a removed source (by id or path), or a removed file (by
path), together with its indexed data — without waiting for the retention
period. Returns a `PurgeResult` (`kind`, `path`). Raises
`SourceNotRemovedError` if the source or file is still active, and
`SourceNotFoundError` if nothing matches.

```python
client.sources.remove(3)
client.sources.purge(3)
```

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

## `PageResult`

A page found by the combined search, returned by `client.search.run_pages`:

- `file_id`, `file_name`, `file_path`, `page_number`, `total_pages`, `duplicate_of_path`, `source`
- `engine` — the strictest engine that found anything on the page (its tier)
- `matched_by` — every engine that did, strictest first
- `score` — what the page was ordered by within its tier: the number of hits (`exact`, `like`), its relevance (`proximity`, `full-text`) or its best word similarity (`fuzzy`)
- `hits` — its `SearchMatch`es, ordered by engine strictness then position; hits that overlap are merged into one

`engine_badge(engine, score=None)` and `hit_badge(match)` give the user-facing labels (`"Exact"`, `"Contains"`, `"Near"`, `"Word"`, `"Similar 83%"`).

## `ProcessingMetric`

- `phase`, `file_type`, `size_bucket`, `document_count`
- `avg_duration_seconds`, `avg_peak_memory_mb`, `avg_cpu_percent`
- `updated_at`

## `SearchMatch`

One occurrence of the query on a page, returned by `client.search.run`:

- `file_id`, `file_name`, `file_path`
- `page_number`, `total_pages` (both `None` for a non-paginated file, e.g. an image)
- `before`, `matched`, `after` (the match split out for highlighting)
- `truncated_before`, `truncated_after`
- `source` (`"native"`, `"ocr"` or `"mixed"` — how the page's text was obtained)
- `score` (higher is better; the `full-text` and `proximity` engines' relevance or the `fuzzy` engine's word similarity, otherwise `None`)
- `duplicate_of_path` (set if this file's content matched an already-indexed file)
- `start`, `end` (where the match sits in the page's text, newlines counted as spaces)
- `engine` (the engine that found it — for the combined search, the strictest that did) and `matched_by` (every engine that found it, strictest first; only set by the combined search)

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
