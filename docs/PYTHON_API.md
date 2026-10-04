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

## `client.version`

A read-only property returning `VersionDetails` with `vethuq` (the installed version), `python`, `platform` and `db_schema` (the database schema version this build supports). It doesn't open the database.

```python
info = client.version
print(info.vethuq, info.python, info.platform, info.db_schema)
```

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

### `rebuild_search(*, on_progress=None)`

Rebuild the full-text search tables from the page text already stored, without
re-reading any file. `on_progress(index, position, total)` is called before each
table. Returns a `SearchIndexRebuildResult`; a table that fails is listed in
`failed` and the others still rebuild. Raises `AlreadyRunningError` while an
index run is active. Unlike the CLI, it doesn't ask for confirmation.

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

### `export(matches, query, output, format_=None, *, engine=None, case_sensitive=False, threshold=None, distance=None, leet_level=None, noise=None, unicode=None)`

Write `matches` for `query` to `output` (a path) as JSON or HTML, and
return the resolved `Path`. `format_` defaults to
`client.settings.search.export_format` if not given, and must be one of
`SEARCH_EXPORT_FORMATS`. Pass the `engine`, `case_sensitive` and (for
`fuzzy` or `proximity`) `threshold` or `distance`, or (for `like` or `noise-fuzzy`) `leet_level`, the
search ran with to record them in the file.

```python
matches = client.search.run("invoice")
client.search.export(matches, "invoice", "results.html", "html")
```

### `run(content, *, context_chars=None, engine=None, case_sensitive=None, threshold=None, distance=None, leet_level=None, noise=None, unicode=None)`

Search indexed OCR text for `content`. Returns one `SearchMatch` per
occurrence, ordered by file path (pages of the same PDF stay in page
order, occurrences within a page in text order) — or best match first for
the `full-text`, `fuzzy`, `proximity` and `noise-fuzzy` engines. Only successfully indexed documents are
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
- `"like"` — `content` anywhere, even inside a word, ignoring case. With `leet_level`
  (`"off"`, `"basic"`, `"standard"` or `"extended"`; default
  `client.settings.search.normalize.leetspeak`, off for `"like"` unless that says
  otherwise) look-alike characters count as the letters they stand for, both ways
  (`"hello"` finds `h3ll0`, `"p@55w0rd"` finds `password`); a `content` under 3 characters or
  without a letter is searched as it is, and `SearchMatch.score` is then the share of it
  matched as typed (1.0 = no look-alike)
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
- `"noise-fuzzy"` — `content`'s characters hidden by stray punctuation or whitespace (letters
  are never noise), look-alike symbols and typos at once: `"hello"` finds `h..e llo`,
  `h @ 3 l l 0`, `h3ll0` and `helo`. It uses `threshold` (as `"fuzzy"`) and `leet_level`
  (single-character look-alikes) too, plus `noise` — one of `SEARCH_NOISE_LEVELS`
  (`"low"` at most 1 noise character in a row and 2 in all, `"medium"` 3 and 6, `"high"` 6
  and 12), defaulting to `client.settings.search.noise_fuzzy.noise`. Cleanest first:
  `SearchMatch.score` is 1.0 for text as typed and falls with each edit, look-alike and
  noise character. No minimum query length

`case_sensitive` defaults to `client.settings.search.case_sensitive`, and
only `"like"`, `"lexical"`, `"fuzzy"` and `"noise-fuzzy"` act on it (`"exact"` is always case-sensitive,
`"full-text"` and `"proximity"` never are; for `"fuzzy"` a difference in case
counts as one edit). `threshold` (`"fuzzy"` and `"noise-fuzzy"` only) is the minimum similarity between
`content`'s words and the words found — `1 − edits ÷ length of the longer
word`, at most 2 edits: a name from `SEARCH_FUZZY_PRESETS` (`"strict"` 90%,
`"balanced"` 80%, `"loose"` 65%), a percentage (`"80%"`) or a number above 0 and up
to 1, defaulting to `client.settings.search.fuzzy.threshold`. `distance`
(`"proximity"` only) is the most words between a passage's first and last term — other
terms in between count: a name from `SEARCH_PROXIMITY_PRESETS` (`"tight"` 3, `"medium"`
10, `"loose"` 30) or a number from 1 to `SEARCH_PROXIMITY_MAX_DISTANCE`, defaulting to
`client.settings.search.proximity.distance`. Raises `SearchOptionError` (a
`ValueError`; its `option` says which argument) for an unknown engine, an invalid
`threshold`, `distance` or `leet_level`, or an explicit `case_sensitive`, `threshold`,
`distance` or `leet_level` the engine can't honour, and `SearchQueryError` (also a `ValueError`) for a `"proximity"`
query of fewer than two terms.

```python
for match in client.search.run("invoice"):
    print(match.file_path, match.matched)
```

### `run_pages(content, *, context_chars=None, case_sensitive=None, threshold=None, distance=None, leet_level=None, noise=None, unicode=None)`

Search with every engine at once and return the pages found, best first, as
`PageResult`s. Pages are ranked by the strictest engine that found them —
`"exact"` (Exact), `"like"` (Contains), `"proximity"` (Near), `"full-text"` (Word),
`"leetspeak"` (Lookalike - `"like"` reading look-alikes), `"fuzzy"` (Similar), `"noise-fuzzy"` (Obscured), in that order (`ENGINE_TIERS`; `ENGINE_BADGES` maps each to the
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

**Unicode** (`unicode=`) treats characters written differently as the same — for `"like"`,
`"fuzzy"` and `"noise-fuzzy"` (and `"exact"` only when passed here); the other engines raise
`SearchOptionError`. It defaults to `client.settings.search.normalize.unicode` (off unless set),
and a search with it on reads every page:

```python
client.search.run("cafe", engine="like", unicode="full")  # finds "café" and "cafe\u0301"
client.search.run("Cafe", engine="exact", unicode="full")  # "Café" - asked for, so applied
client.search.run("cafe", engine="fuzzy", unicode="full")  # an accent is no longer an edit
client.search.run("cafe", engine="full-text", unicode="full")  # raises SearchOptionError
```

**Look-alikes** (`leet_level`) with `"like"`:

```python
client.search.run("hello", engine="like", leet_level="basic")  # "hello", "h3ll0", "He11o"
client.search.run("p@55w0rd", engine="like", leet_level="basic")  # "password", "p@55w0rd"
client.search.run("hello", engine="like", leet_level="basic", case_sensitive=True)  # not "H3LL0"
client.search.run("game", engine="like", leet_level="standard")  # also "9ame"
client.search.run("hello", engine="fuzzy", leet_level="basic")  # raises SearchOptionError
```

**`"noise-fuzzy"`** finds text hidden by noise, look-alikes and typos together:

```python
client.search.run("hello", engine="noise-fuzzy")  # "he llo", "h3ll0", "helo", "hallo"
client.search.run("hello", engine="noise-fuzzy", noise="medium")  # also "h..e llo"
client.search.run("hello", engine="noise-fuzzy", noise="high")  # also "h @ e # l l o"
client.search.run("password", engine="noise-fuzzy", threshold="strict", leet_level="standard")
client.search.run("hello", engine="like", noise="low")  # raises SearchOptionError
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
  the `like`, `lexical`, `fuzzy` and `noise-fuzzy` engines act on it; the same as
  `client.settings.search.normalize.case` being `"match"`)
- `set(enabled)`

### `client.settings.search.engine`

- `get()` — default engine `search` uses (`"all"` by default: every engine, ranked together)
- `set(engine)` — `engine` must be one of `SEARCH_ENGINES` (`"all"`, `"like"`, `"exact"`,
  `"full-text"`, `"fuzzy"`, `"proximity"`, `"noise-fuzzy"`); raises `InvalidSettingValueError`
  otherwise

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

### `client.settings.search.normalize.case`

- `get()` — whether upper and lower case are the same letter, a name from `SEARCH_CASE_VALUES`:
  `"auto"` (the default — each engine's own), `"ignore"` or `"match"`
- `set(value)` — one of those, for the engines that can honour it (`like`, `lexical`,
  `fuzzy`, `noise-fuzzy`); raises `InvalidSettingValueError` otherwise

### `client.settings.search.normalize.unicode`

- `get()` — whether characters written differently count as the same, a name from
  `SEARCH_UNICODE_VALUES`: `"auto"` (the default — each engine's own, which is off for all of
  them for now), `"off"`, `"basic"` or `"full"`
- `set(value)` — one of those (`SEARCH_UNICODE_LEVELS` lists the three): `"basic"` composes
  characters and keeps accents, `"full"` also folds accents and compatibility forms (`cafe` finds
  `café`). Honoured by `like`, `fuzzy` and `noise-fuzzy`, and by `exact` only when `unicode=` is
  passed to `search.run`; raises `InvalidSettingValueError` otherwise

### `client.settings.search.normalize.leetspeak`

- `get()` — whether look-alike characters (`3` for `e`, `@` for `a`) count as the letters they
  stand for, a name from `SEARCH_LEETSPEAK_VALUES`: `"auto"` (the default — each engine's own:
  `"basic"` for `noise-fuzzy` and the combined search, none for `like`), `"off"`, `"basic"`,
  `"standard"` or `"extended"`
- `set(value)` — one of those; each level includes the one before it (`SEARCH_LEETSPEAK_LEVELS`
  lists the three). The substitution table is built in. Honoured by `like` and `noise-fuzzy`;
  raises `InvalidSettingValueError` otherwise

### `client.settings.search.noise_fuzzy.noise`

- `get()` — the stored default noise level for the `noise-fuzzy` engine, a name from
  `SEARCH_NOISE_LEVELS` (`"low"` by default)
- `set(level)` — `"low"` (at most 1 noise character in a row, 2 in all), `"medium"` (3 and 6)
  or `"high"` (6 and 12); raises `InvalidSettingValueError` otherwise

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

## `SearchIndexRebuildResult`

The outcome of `index.rebuild_search`:

- `rebuilt` (table name → page count), `failed` (table name → error message)
- `seconds` (time taken), `ok` (`True` when nothing failed)

## `IntegrityCheckResult`

The outcome of a database integrity check, returned by `client.db.integrity_check`:

- `ok` (`True` when the database is intact)
- `errors` (the problems SQLite reported; empty when `ok`)

## `PageResult`

A page found by the combined search, returned by `client.search.run_pages`:

- `file_id`, `file_name`, `file_path`, `page_number`, `total_pages`, `duplicate_of_path`, `source`
- `engine` — the strictest engine that found anything on the page (its tier)
- `matched_by` — every engine that did, strictest first
- `score` — what the page was ordered by within its tier: the number of hits (`exact`, `like`), its relevance (`proximity`, `full-text`), the share of the query matched as typed (`leetspeak`), its best word similarity (`fuzzy`) or its cleanliness (`noise-fuzzy`)
- `hits` — its `SearchMatch`es, ordered by engine strictness then position; hits that overlap are merged into one

`engine_badge(engine, score=None)` and `hit_badge(match)` give the user-facing labels (`"Exact"`, `"Contains"`, `"Near"`, `"Word"`, `"Lookalike"`, `"Similar 83%"`, `"Obscured"`).

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
- `score` (higher is better; the `full-text` and `proximity` engines' relevance or the `fuzzy` engine's word similarity or the `leetspeak` engine's share matched as typed, otherwise `None`)
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

`StartupError` is the base class for problems that stop VethuQ starting or running:
`InvalidConfigError`, `DataFolderNotWritableError`, `CorruptDatabaseError`,
`OcrModelMissingError`, `SchemaVersionError` and `StaleLockError`. Each has a `message` (what is
wrong), a `hint` (what to do) and the `exit_code` the CLI exits with; `str(error)` joins the
message and hint. `import vethuq` itself raises one of these if the settings or data folder
are unusable, and `client.index.run(...)` raises `OcrModelMissingError` if the OCR engine isn't
installed. See [docs/troubleshooting.md](troubleshooting.md) for what each means and how to fix
it.

```python
try:
    client = vethuq.Vethuq()
    client.db.integrity_check()
except vethuq.StartupError as exc:
    print(exc.message, "-", exc.hint)
```

`SourceError` is the base class for `SourceAlreadyExistsError`,
`SourceNotFoundError`, and `SourcePathError` — catch `SourceError` to
handle any of them generically, or a specific subclass to handle one case.

`IndexRunnerError` is the base class for `AlreadyRunningError` and
`StaleLockError` (which is also a `StartupError`), raised by the indexing methods above.

`SettingsError` is the base class for `InvalidSettingValueError`, raised by
the `set(...)` methods under `client.settings` when given an invalid value
(it's also a `ValueError`, so existing `except ValueError` handling still
works).
