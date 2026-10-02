# CLI reference

Install with `pip install vethuq` (Windows or Linux, Python 3.11+) — this
also gives you `import vethuq` as a library, see
[docs/PYTHON_API.md](PYTHON_API.md).

The `vethuq` command-line tool manages sources (files/folders registered
for OCR/indexing), runs the OCR indexing pipeline, and configures
settings.

## `db`

### `integrity-check`

Check the database for corruption now and print the result. Exits with a non-zero status and lists the problems SQLite found if the check fails; the outcome is also logged.

```bash
vethuq db integrity-check
```

## `index`

### `history [--limit N] [--json]`

List past background index runs (target, status, files
processed/failed, start/end time), most recent first. `--limit` caps how
many are shown (default 10).

```bash
vethuq index history
vethuq index history --limit 25 --json
```

### `pause` / `resume`

Pause or resume the currently running background index. Pausing takes
effect after the file currently being processed finishes; the run stays
alive, waiting to be resumed.

```bash
vethuq index pause
vethuq index resume
```

### `restart [source] [--wait] [--force]`

Retry only files that previously failed OCR, as a background process.
Unlike `run`, new files and already-indexed files are left untouched —
only files whose last attempt errored are (re)processed. Takes the same
`source`/`--wait`/`--force` options as `run`.

```bash
vethuq index restart
vethuq index restart ./path/to/folder-or-file
```

### `run [source] [--wait] [--force]`

Start OCR indexing as a background process and return immediately. A
freshly added/reactivated (`pending`) source is (re)processed in full; an
already-`indexed`/`error` source is checked for files added or modified
since the last run — a file's checksum is compared against the last time
it was indexed, and only new, modified, or previously failed files are
processed, while unchanged files are left untouched. A file that was
renamed or moved within the source is recognized by its unchanged content
and simply relabeled, without re-running OCR on it; a file that's gone
missing from the source is flagged and automatically cleaned up after a
retention period (like a removed source — see `vethuq settings` below).
Extracts text (English; PDF, PNG, and JPEG files supported) and stores it
locally. PDF pages with a real text layer are read directly from it; OCR
only runs on scanned pages/regions.

Pass a source id or path to index only that source; omit it to index
every active source. `--wait` blocks until the run finishes, printing
progress as it goes, instead of returning immediately. `--force` clears
a lock left behind by a previous run that didn't exit cleanly (e.g. after
a crash) — without it, `run` refuses to start a second run on top of one
that might still be alive.

```bash
vethuq index run
vethuq index run ./path/to/folder-or-file
vethuq index run 3 --wait
vethuq index run --force
```

### `status [source] [--json]`

Without a source, shows the current (or most recently finished)
background run: status, progress (`processed/total`), failed-file count,
the file currently being processed, and an ETA while running. With a
source id or path, shows a detailed per-file breakdown for that source
instead (status, confidence, and duration for each file). A file whose
content exactly matches an already-indexed file is shown as a duplicate
of that file instead of being OCR'd again. `--json` prints
machine-readable output (adds a `duplicate_of` field, null unless the
file is a duplicate).

```bash
vethuq index status
vethuq index status ./path/to/folder-or-file
vethuq index status 3 --json
```

### `stop`

Stop the currently running background index. Requests a graceful stop
first and force-terminates the process if it doesn't exit promptly.

```bash
vethuq index stop
```

## `logs [component]`

List VethuQ's log files, or read one: `database`, `index`, `ui` or `cli` (see
[Data layout](architecture.md#data-layout)). Shows the most recent entries of
today's log — an entry is one log line plus any traceback under it.

Options:

- `--tail N` / `-n N` — how many entries to show (default 40)
- `--follow` / `-f` — keep printing new entries as they're written; Ctrl+C stops
- `--level LEVEL` — only entries at or above `debug`, `info`, `warning` or `error`
- `--date YYYY-MM-DD` — read that day's rotated log instead of today's
- `--export FILE` — write the selected entries to `FILE` instead of printing them

`--follow` can't be combined with `--date` or `--export`.

```bash
vethuq logs
vethuq logs index --tail 40
vethuq logs index --level warning --date 2026-09-28
vethuq logs cli -f
vethuq logs database --tail 200 --export database-log.txt
```

## `search <content> [--engine like|exact|full-text|fuzzy|proximity] [--case-sensitive|--no-case-sensitive] [--threshold N|--fuzziness NAME] [--distance N|NAME]`

Search indexed content for `content` and print matching pages. Only
documents with status `indexed` are searched. `--engine` chooses how
`content` is matched (default `like`, or `vethuq settings search engine`):

| Engine | Matches | `Museum` in "Visit the Museum" |
|---|---|---|
| `like` | `content` anywhere, even inside a word; ignores case unless `--case-sensitive` | `museum`, `Museum`, `mus`, `seu` ✓ — `Museums`, `euma` ✗ |
| `exact` | `content` as typed: same case, as a whole word (always case-sensitive) | `Museum` ✓ — `museum`, `Museums`, `mus` ✗ |
| `full-text` | pages containing `content`'s words: any case, English word forms (`museums`), accents folded; best matches first | `museum`, `MUSEUM`, `Museums`, `mus*` ✓ — `mus`, `seu` ✗ |
| `fuzzy` | pages containing words *close to* `content`'s, tolerating typos and OCR misreads; closest first | `Museum`, `Museums`, `Muzeum`, `Musuem`, `Musem` ✓ — `Museurn` (loose only), `mus`, `Mustard` ✗ |
| `proximity` | passages where all of `content`'s words (two or more, any order) occur within N words of each other; one result per passage | `payment termination` finds "…the **payment** is due within thirty days, subject to the **termination**…" with `--distance 8` or more, not with `tight` |

For `full-text`, all the words must appear on the page (`"amount due"` in
quotes must appear as that phrase), and a trailing `*` makes a word a prefix
(`mus*` finds `museum`). Punctuation and words like `AND` or `NEAR` are
searched as plain text, not operators.

`fuzzy` matches whole words at a time, and every word of `content` must be
matched. Two words are *similar* when `1 − edits ÷ length of the longer word`
reaches the threshold, where an edit is an insertion, deletion, substitution
or swap of two neighbouring letters, and at most 2 edits are ever allowed.
Words under 4 letters and any word containing a digit (identifiers, amounts,
dates) must match exactly — a near-miss there is a different thing, not a
typo. `--threshold` takes a percentage (`80%`, or just `80`) or a number above
0 and up to 1 (`0.8`); `--fuzziness` takes a name for one: `strict` (90% —
little beyond plurals), `balanced` (80%, the default — also a typo in a longer
word) or `loose` (65% — heavier OCR damage such as `Museurn`, with more noise).
Give one or the other; the default comes from `vethuq settings search fuzzy
threshold`. Each result shows its similarity, and `--threshold`/`--fuzziness`
are errors with any other engine (a stored threshold is just not applied there).

`proximity` finds passages where all of `content`'s terms sit close together.
A term is a word or a `"quoted phrase"` (a trailing `*` makes a word a prefix),
at least two are needed, and they may appear in any order; each matches as in
`full-text` (any case, English word forms). `--distance` is the most words that
may lie between the first and the last term of a passage — other terms in
between count as words — as a number from 1 to 100 or a name: `tight` (3 words —
the same phrase), `medium` (10, the default — the same clause or sentence) or
`loose` (30 — the same paragraph). The default comes from `vethuq settings
search proximity distance`. Each passage is one result, from its first term to
its last, on pages ranked by relevance; passages on a page appear in text
order. `--distance` is an error with any other engine (a stored distance is just
not applied there), and `proximity` is never case-sensitive. A distance of 0
would be an exact phrase, which `full-text` already does with quotes. Prefix
queries are stemmed like any other term, so a prefix that isn't itself a word
stem (`pay*` — stemmed to `pai*`) may miss words it looks like it covers.

`--case-sensitive` / `--no-case-sensitive` overrides
`vethuq settings search case-sensitive`, and only `like` and `fuzzy` act on it
(for `fuzzy` a difference in case counts as one edit):
`exact` is always case-sensitive while `full-text` and `proximity` never are,
so asking for the opposite explicitly (`--engine exact --no-case-sensitive`,
`--engine full-text --case-sensitive`) is an error, while a stored
preference the engine can't honour is simply not applied. The header of
the results shows which engine (with its case-sensitivity, threshold or
distance) produced them, and an empty `exact`, `full-text`, `fuzzy` or
`proximity` search suggests a looser search.
Results open in a pager, starting at the top: scroll (e.g. the
down arrow, space, or page down) to reveal more, and press `q` to close
it. Each file with a match prints its path once, followed by a
`Page: X of Y` and boxed, highlighted snippet for every match in
that file (PDFs only show `Page:` — an image is a single page). A
duplicate file (identical content to another already-indexed file) is
still shown as its own result, reusing the original's matched text, with
its `File:` line noting which file it's a duplicate of:

```bash
Results: 3 matches

File: <full file path>
Page: <page number> of <total pages in the file>   (PDFs only)

________________________________________
|                                       |
|   ...surrounding text with the MATCH  |
|   highlighted, wrapped to fit...      |
|_______________________________________|

Page: <next matching page> of <total pages in the file>

________________________________________
|                                       |
|   ...another matching page's snippet  |
|_______________________________________|

File: <next file's full path>
...
```

Consecutive files alternate accent colors so results are easier to tell
apart. When a page contains the search term more than once, each
occurrence gets its own box. The box's width and how much surrounding text
it shows are controlled by `vethuq settings search snippet` (80
characters by default).

On Windows, this uses `less` (bundled with Git for Windows) if it's on
your `PATH`, for proper arrow-key scrolling and colors; without it,
Windows' built-in `more` is used instead, which only advances a line at
a time on Enter and doesn't render colors.

```bash
vethuq search "invoice total"
```

Examples, assuming a page that reads "Learn English at the English Institute":

**`like`** (the default) finds the text anywhere, even inside a word:

```bash
vethuq search eng                                   # case-insensitive: finds "English" (twice)
vethuq search english --engine like                 # case-insensitive: finds "English"
vethuq search English --case-sensitive              # case-sensitive: finds "English"
vethuq search english --case-sensitive              # case-sensitive: no match ("english" ≠ "English")
vethuq search ENGLISH --no-case-sensitive           # case-insensitive, even if the setting is on
```

**`exact`** finds the text as typed, as a whole word. It is always
case-sensitive, so `--case-sensitive` is allowed but redundant, and
`--no-case-sensitive` is an error:

```bash
vethuq search English --engine exact                # finds "English"
vethuq search english --engine exact                # no match: wrong case
vethuq search eng --engine exact                    # no match: only part of a word
vethuq search "English Institute" --engine exact    # finds the phrase as typed
vethuq search English --engine exact --case-sensitive       # same as the first example
vethuq search English --engine exact --no-case-sensitive    # error: always case-sensitive
```

**`full-text`** finds pages containing the words, in any form, best
matches first. It is always case-insensitive, so `--no-case-sensitive` is
allowed but redundant, and `--case-sensitive` is an error:

```bash
vethuq search english --engine full-text            # finds "English", any case
vethuq search ENGLISH --engine full-text            # same results
vethuq search "eng*" --engine full-text             # prefix: finds "English", "engine", "engineering"...
vethuq search eng --engine full-text                # no match: not a whole word
vethuq search "english institute" --engine full-text       # both words on the page, any order
vethuq search '"english institute"' --engine full-text     # the exact phrase, words adjacent and in order
vethuq search english --engine full-text --no-case-sensitive    # same as the first example
vethuq search english --engine full-text --case-sensitive       # error: always case-insensitive
```

**`fuzzy`** finds words close to yours, closest first:

```bash
vethuq search Museum --engine fuzzy                   # finds "Muzeum", "Musuem", "Museums"
vethuq search Museum --engine fuzzy --fuzziness loose # also "Museurn"
vethuq search Museum --engine fuzzy --threshold 70%   # a percentage instead of a name
```

**`proximity`** finds passages where all your words sit close together:

```bash
vethuq search "payment termination" --engine proximity                    # within 10 words (the default)
vethuq search "payment termination" --engine proximity --distance loose   # within 30 words
vethuq search "late fee" --engine proximity --distance 5                  # within 5 words
```

To make an engine, case-sensitivity, fuzzy threshold or proximity distance the default for every
search, see `vethuq settings search engine`, `case-sensitive`, `fuzzy threshold` and
`proximity distance`
below. In PowerShell, put a quoted phrase inside single quotes, as in the
`'"english institute"'` example.

## `settings`

### `db integrity-check`

Configure whether VethuQ checks the database for corruption (`PRAGMA integrity_check`) when it's opened. One of `auto` (the default — at most once per interval), `enable` (every time it's opened), or `disable` (only when you run `vethuq db integrity-check`). The interval for `auto` defaults to 1 day (1440 minutes).

```bash
vethuq settings db integrity-check set auto
vethuq settings db integrity-check show
vethuq settings db integrity-check interval set 60
vethuq settings db integrity-check interval show
```

### `gpu enable|disable|status`

Configure whether OCR should attempt to use the GPU. Disabled by
default. Enabling it only has an effect if a CUDA-capable PaddlePaddle
build with a visible GPU is actually installed — otherwise OCR silently
falls back to CPU.

```bash
vethuq settings gpu enable
vethuq settings gpu disable
vethuq settings gpu status
```

### `index removed-retention set <minutes>|show`

Configure, in minutes, how long a removed source (and its indexed data)
is kept before it's permanently deleted from the database. Defaults to
7 days (10080 minutes). The purge itself runs opportunistically whenever a database
connection is opened (CLI commands, the desktop app), not on a fixed
schedule.

```bash
vethuq settings index removed-retention set 60
vethuq settings index removed-retention show
```

### `index stability-check set <seconds>|show`

Before indexing a file, VethuQ checks that its size and modified time are
unchanged across two checks this many seconds apart. A file still being
copied or downloaded fails the check and is left for the next scan; a file
that changes while it's being read has its result discarded and is retried
(up to the `ocr retry` count) before being marked as an error. Defaults to 1
second; `0` disables the check.

```bash
vethuq settings index stability-check set 2
vethuq settings index stability-check show
```

### `index stale-lock set <value>|show`

Configure whether a lock left behind by an indexing run that didn't exit
cleanly (a crash, power loss) is cleared automatically on the next run. One
of `auto` (the default — clears it), `enable` (clears it, an explicit opt-in
with the same effect as `auto`), or `disable` (the next run needs `--force`).

```bash
vethuq settings index stale-lock set disable
vethuq settings index stale-lock show
```

### `index thread-workers set <value>|show`

Configure how many worker threads background indexing uses. `0` (the
default) indexes one file at a time; `1`-`8` is a fixed worker count; `auto`
sizes the pool to current CPU and memory headroom throughout the run.

```bash
vethuq settings index thread-workers set auto
vethuq settings index thread-workers show
```

### `logs level set <level>|show`

Configure how verbose VethuQ's log files (`database.log`, `index.log`, `ui.log`,
`cli.log` in the `logs/` folder, see [Data layout](architecture.md#data-layout))
are: `debug`, `info` (default), `warning` or `error`. It applies to processes
started after the change.

```bash
vethuq settings logs level set debug
vethuq settings logs level show
```

### `logs retention set <days>|show`

Each log file starts a new file every day (`index.log.2026-09-28`, ...). This
sets how many days of daily files are kept before they're deleted; defaults to
15, minimum 1. It applies to processes started after the change.

```bash
vethuq settings logs retention set 30
vethuq settings logs retention show
```

### `ocr engine set <mode>|show`

Configure how thoroughly OCR looks for rotated text. One of `quick` (the
default — upright text only), `moderate` (also 90°, 180° and 270°), or `deep`
(also every 15° in between). Each includes the ones before it. Files are
always indexed `quick` first so they're searchable right away; the deeper
passes then run in the background, moderate before deep, and any new or
changed file gets its quick pass before deeper work continues. Raising the
setting deepens already-indexed files the next time indexing runs; lowering
it never removes text. `vethuq index status` shows the current phase.

```bash
vethuq settings ocr engine set moderate
vethuq settings ocr engine show
```

### `ocr retry set <attempts>|show`

Configure how many times a file's OCR is retried after a transient failure
before the file is marked as an error. Defaults to 3; `0` disables retries.
A file that's missing, password-protected or corrupted fails immediately
without retrying.

```bash
vethuq settings ocr retry set 5
vethuq settings ocr retry show
```

### `search export-format set <format>|show`

Configure the default format `vethuq search --export` writes to when none is
given: `json` (the default) or `html`.

```bash
vethuq settings search export-format set html
vethuq settings search export-format show
```

### `search engine set <engine>|show`

Configure the engine `vethuq search` uses when `--engine` isn't given: one
of `like` (the default), `exact`, `full-text`, `fuzzy` or `proximity`.

```bash
vethuq settings search engine set full-text
vethuq settings search engine show
```

### `search case-sensitive enable|disable|show`

Configure whether `vethuq search` matches case by default. Disabled by
default. Only the `like` and `fuzzy` engines act on it; `--case-sensitive` /
`--no-case-sensitive` overrides it for one search.

```bash
vethuq settings search case-sensitive enable
vethuq settings search case-sensitive disable
vethuq settings search case-sensitive show
```

### `search fuzzy threshold set <threshold>|show`

Configure how close a word must be to your query for `vethuq search
--engine fuzzy` to match it, when `--threshold`/`--fuzziness` isn't given:
`strict` (90%), `balanced` (80%, the default), `loose` (65%), a percentage
(`75%`) or a similarity above 0 and up to 1 (`0.75`).

```bash
vethuq settings search fuzzy threshold set loose
vethuq settings search fuzzy threshold set 75%
vethuq settings search fuzzy threshold show
```

### `search proximity distance set <distance>|show`

Configure the most words `vethuq search --engine proximity` allows between its
first and last term, when `--distance` isn't given: `tight` (3 words),
`medium` (10, the default), `loose` (30), or a number of words from 1 to 100.

```bash
vethuq settings search proximity distance set loose
vethuq settings search proximity distance set 15
vethuq settings search proximity distance show
```

### `search snippet set <chars>|show`

Configure how many characters of context `vethuq search` shows on each
side of a match. Defaults to 80.

```bash
vethuq settings search snippet set 40
vethuq settings search snippet show
```

## `source`

### `add <path>`

Register a file or folder as a source. Folders are indexed recursively.
Prints a hint to run `vethuq index run` once added — adding a source
does not index it automatically.

```bash
vethuq source add ./path/to/folder-or-file
```

### `list`

List all registered (active) sources, most recently added first, with
their id, type (`file`/`folder`), and status (`pending`/`indexed`/`error`).

```bash
vethuq source list
```

### `list <id-or-path> [--detail]`

List every file tracked under a source (by id or path): the file's id, its
name (relative to the source, for a folder), and its index status
(`pending`/`processing`/`indexed`/`error`).

```bash
vethuq source list 3
vethuq source list ./path/to/folder
```

With `--detail`, each file also shows its type, size, page count,
started/completed/indexed timestamps, duration, confidence, current OCR
phase and the angles read so far, the timing of each deeper OCR phase (see
[ocr-phases.md](ocr-phases.md)), retries, the original it duplicates, and
any error. `--detail` requires a source id or path.

```bash
vethuq source list 3 --detail
```

Also available from the interactive menu under Sources > List Files.

### Exporting a listing

`list` (with or without a source, and with or without `--detail`) accepts
`--export <file>` and `--format json|html`, exactly like `vethuq search`:
the listing is written to the file instead of being printed. `--format`
defaults to `vethuq settings search export-format` and needs `--export`.

```bash
vethuq source list --export sources.json
vethuq source list 3 --export files.html --format html
vethuq source list 3 --detail --export files.json --format json
```

The interactive menu asks for an export file (blank to just print) after
List and List Files.

### `remove <id-or-path>`

Remove a registered source (soft-delete — the source stops being
processed but its history isn't erased). Accepts either the source's id
(from `source list`) or its path.

```bash
vethuq source remove 3
vethuq source remove ./path/to/folder-or-file
```

## `stats`

### `reset [--force]`

Clear both statistics tables. Asks for confirmation first unless
`--force` is given — resetting means `vethuq index run`'s ETA is
unavailable again until enough files have been (re)indexed to rebuild
the averages.

```bash
vethuq stats reset
vethuq stats reset --force
```

### `show`

Show accumulated OCR statistics in two panels: Processing (per file
type — documents indexed, average duration, average peak memory,
average CPU) and Confidence (per file type and text-source — native,
OCR, mixed — page count and average confidence). Both are running
averages folded in after each successfully indexed document/page; the
Processing figures also feed `vethuq index run`'s ETA estimate.

```bash
vethuq stats show
```
