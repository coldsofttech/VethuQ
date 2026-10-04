# CLI reference

Install with `pip install vethuq` (Windows or Linux, Python 3.11+) — this
also gives you `import vethuq` as a library, see
[docs/PYTHON_API.md](PYTHON_API.md).

The `vethuq` command-line tool manages sources (files/folders registered
for OCR/indexing), runs the OCR indexing pipeline, and configures
settings.

If VethuQ can't start (invalid settings, an unwritable data folder, a damaged database, missing
OCR models), it prints what is wrong and what to do, then exits with a code specific to the
problem (10-15). See [docs/troubleshooting.md](troubleshooting.md).

## `--version`

Show the VethuQ version, Python version, platform and database schema version in a panel, then exit. Handy to include when asking for support.

```
vethuq --version
```

## `db`

### `integrity-check`

Check the database for corruption now and print the result. Exits with a non-zero status and lists the problems SQLite found if the check fails; the outcome is also logged.

```bash
vethuq db integrity-check
```

### `backup create [NAME]`

Take a compressed backup of the database now. Give it a `NAME` to keep a snapshot that is never deleted automatically; otherwise it is timestamped. A database that fails its integrity check is not backed up.

```bash
vethuq db backup create before-upgrade
```

### `backup list`

List the backups, newest first, with their kind (`auto`, `safety` or `manual`), date and size.

### `backup delete NAME [--force]`

Delete one backup (asks first; `--force` skips the question).

### `restore NAME_OR_PATH [--force]`

Replace the database with a backup, given by name (see `backup list`) or by the path of a `.db.gz` file. The backup is checked first, and the database you are replacing is saved as a `safety-...` backup, so a restore can be undone. Asks first; `--force` skips the question. Not available while an index run is in progress.

### `repair`

Rebuild the database's indexes and check it again. This fixes corruption that is limited to indexes; if the check still fails it says so and points to `restore` and `reset`. A `safety-...` backup is taken first.

### `reset [--force]`

Delete the database and everything in it — registered sources, the search index and settings (your files themselves are untouched). A `safety-...` backup is taken first, and a fresh database is created the next time VethuQ runs. Asks first; `--force` skips the question.

### Automatic backups

VethuQ takes a compressed backup automatically the first time it opens the database each day and keeps `auto-...` and `safety-...` backups for 7 days (always keeping the newest three). Backups live in a `backups` folder next to the database (or wherever `vethuq settings location backups set` points). A schema upgrade also saves a `safety-premigration-...` backup first. If an index run has to recover from a crash or a forced stop, VethuQ checks the database first and stops with instructions if it is damaged. Tune this under `vethuq settings db backup`.

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

### `reindex <source> [--wait] [--force]` / `reindex file <id-or-path> [--source <id-or-path>] [--wait] [--force]`

Re-index everything under a source, or one file, regardless of whether it
already succeeded. Files are OCR'd again and their existing documents are
updated in place, so no duplicate logical documents appear. Refused while
another index run is active. `file` is reserved: address a source literally
named `file` by its id. If a file sits under more than one source,
`reindex file` fails and asks for `--source`.

```bash
vethuq index reindex 3
vethuq index reindex file ./docs/invoice.pdf --source 3
```

### `rebuild-search [--force]`

Rebuild the full-text search tables (a trigram and a word index per kind of page, plus the
trigram index over each page's noise-free skeleton and one over its normalized text) from the page text already stored in the
database; files are not re-read or re-OCR'd. Use it if search results look
incomplete or out of date. Asks for confirmation unless `--force` is given,
shows progress while it runs, then a panel with one row per table (rebuilt or
failed, with its page count). A table that fails doesn't stop the others;
the command then exits non-zero. Refused while an index run is active.
Results are also recorded in the index log.

```bash
vethuq index rebuild-search
vethuq index rebuild-search --force
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

## `search <content> [--engine all|like|exact|full-text|fuzzy|proximity|noise-fuzzy] [--case-sensitive|--no-case-sensitive] [--threshold N|--fuzziness NAME] [--distance N|NAME] [--leet-level LEVEL] [--noise LEVEL] [--normalize NAME=VALUE]`

Search indexed content for `content` and print matching pages. Only
documents with status `indexed` are searched. `--engine` chooses how
`content` is matched — by default (`all`, or `vethuq settings search engine`)
every engine runs and the pages are ranked together (below); any other value
runs just that engine:

| Engine | Matches | `Museum` in "Visit the Museum" |
|---|---|---|
| `like` | `content` anywhere, even inside a word; ignores case unless `--case-sensitive`; with `--leet-level`, look-alikes (`3` for `e`) count as the letters | `museum`, `Museum`, `mus`, `seu` ✓ — `Museums`, `euma` ✗ |
| `exact` | `content` as typed: same case, as a whole word (always case-sensitive) | `Museum` ✓ — `museum`, `Museums`, `mus` ✗ |
| `full-text` | pages containing `content`'s words: any case, English word forms (`museums`), accents folded; best matches first | `museum`, `MUSEUM`, `Museums`, `mus*` ✓ — `mus`, `seu` ✗ |
| `fuzzy` | pages containing words *close to* `content`'s, tolerating typos and OCR misreads; closest first | `Museum`, `Museums`, `Muzeum`, `Musuem`, `Musem` ✓ — `Museurn` (loose only), `mus`, `Mustard` ✗ |
| `proximity` | passages where all of `content`'s words (two or more, any order) occur within N words of each other; one result per passage | `payment termination` finds "…the **payment** is due within thirty days, subject to the **termination**…" with `--distance 8` or more, not with `tight` |
| `noise-fuzzy` | `content`'s characters hidden by stray punctuation or whitespace, look-alike symbols and typos *at once*; cleanest first | `hello` finds `hello`, `helo`, `hallo`, `h3ll0`, `he llo`, `h.ello`; with `--noise medium` also `h..e llo` and `h @ 3 l l 0` ✓ — `hxexlxlxo` ✗ |

### `--engine all` (the default): every engine, ranked together

The engines answer different questions and their scores can't be compared, so
pages are ranked by **how strictly they matched** — the strictest engine that
found a page decides its tier — and only within a tier by that engine's own
signal:

| Tier | Engine | Page label | Ordered within the tier by |
|---|---|---|---|
| 1 | `exact` | **Exact** | number of matches on the page |
| 2 | `like` | **Contains** | number of matches on the page |
| 3 | `proximity` | **Near** | relevance |
| 4 | `full-text` | **Word** | relevance |
| 5 | `fuzzy` | **Similar 83%** | best word similarity |
| 6 | `noise-fuzzy` | **Obscured** | cleanliness: fewest edits, look-alikes and noise characters |

`proximity` ranks above `full-text` because every page it finds `full-text`
finds too (both need all the words), so the other way round "the words are close
together" could never raise a page. `noise-fuzzy` ranks last: it is `fuzzy` with
tolerance for stray characters, so every page `fuzzy` finds it finds too (**Obscured**).

A normalization is a **modifier** of an engine's label, not a tier of its own: a `like` hit
written `h3ll0` is **Contains · look-alike**, one that needed accents read as plain letters
(`unicode=full`) is **Contains · accents**. A hit that needed a modifier ranks after every page
matched as typed (whatever engine) and before the approximate engines (**Similar**,
**Obscured**), then by engine as usual; among look-alike pages, the less disguised comes first.
The `h` legend in the pager lists them.
Ties go to the page more engines agree on, then to file path and page.

Because the engines' matches nest — an exact match is also a substring, a word
and a similar word — a good match is usually found by three or four of them, so
each **page is listed once**, labelled with its strictest engine and the others
that found it, and hits that overlap are merged into one:

```
Results: 2 pages (engine: all)

contract.pdf
File: /docs/contract.pdf
Page: 3 of 12 [ocr] [Exact]  also: Contains, Word, Similar

<box: the best hit, ...the Museum of...>

[Similar 83%]
<box: a weaker hit on the same page, ...the Muzeum shop...>

+2 more matches on this page
```

The label after `[ocr]` is the page's tier; a hit found less strictly than the
page's best carries its own label; a page shows its best three hits (best engine
first, then by position) and counts the rest. A `proximity` passage swallows the
word hits inside it. Each engine applies the options it can: `--case-sensitive`
reaches `like`, `fuzzy`, `leetspeak` and `noise-fuzzy` (`exact` always matches case, `full-text` and
`proximity` never do), `--threshold`/`--fuzziness` only `fuzzy`, `--distance`
only `proximity`, each defaulting to its setting — and `all` never rejects an
option. `proximity` is skipped for a query of fewer than two terms. Exports list
every hit with its `engine` and `matched_by` (and a Match column in HTML).

### The single engines

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

**Normalizations** decide what counts as *the same character*, for `content` and the page
alike, whichever engine decides the shape of the match: `--normalize NAME=VALUE` (repeat the
flag, or separate with commas) with `unicode=off|basic|full`, `case=ignore|match` (the same as
`--no-case-sensitive` / `--case-sensitive`) and `leetspeak=off|basic|standard|extended` (the
same as `--leet-level`); each one is also a setting under `vethuq settings search normalize`
(`auto` unless changed: every engine uses its own default). Giving the same one twice is an
error.

**Unicode** (`unicode=`) treats characters that are written differently as the same: `basic`
composes them (an `e` followed by a separate accent is `é`, which is how some PDFs write it)
and keeps accents; `full` also folds accents and compatibility forms, so `cafe` finds `café`
and `naive` finds `naïve`, `fine` finds the ligature `ﬁne`, full-width `ＡＢＣ` is `ABC` and
`x2` finds `x²`. It applies to `like`, `exact`, `fuzzy` and `noise-fuzzy`. Each engine has its own default:
`exact` and `like` `basic` (so a decomposed `é` is found either way, but `cafe` still isn't
`café`), `fuzzy` and `noise-fuzzy` `full` (an accent is no longer an edit). `exact` is strict: a
stored setting doesn't reach it, only `--normalize unicode=...` in that search. `full-text`
already folds accents (and accepts no setting), `lexical` and `proximity` take none; they reject
it. Highlights and exports show the original text. The searches still use the text indexes (the
database records each page's normalized text), so a level never needs a reindex; run `index
rebuild-search` once after upgrading from a version that predates it.

**Look-alike characters (leetspeak)** are a normalization, not an engine: what counts as
the same character, applied to `content` and to the page alike, whichever engine decides
the shape of the match. With them on, `hello` finds `h3ll0` and `h3ll0` finds `hello`;
`password` finds `p@55w0rd`. Two characters match when they can stand for the same
letter, so an ambiguous one such as `1` (`i` or `l`) matches either, and for `like` it
is still a substring match. It needs a `content` of at least 3 characters with a letter
among them (digits and symbols alone, like `2024`, are searched as they are). The
substitutions are built in — nothing to manage — at three levels, each including the
one before it: `basic` (`0` `1` `3` `4` `5` `7` `@` `$`), `standard` (adds `2` `6` `8` `9`
`+` `!` `|`) and `extended` (adds `(` `[` `{` for `c`); `off` reads none. Which engines
honour it, and their defaults:

| Engine | Look-alikes by default | Set with |
|---|---|---|
| `like` | off | `--leet-level`, or `vethuq settings search normalize leetspeak` |
| `noise-fuzzy` | `basic` | the same (`off` turns them off: a `3` is then a typo) |
| the default `all` search | `basic`, for its **look-alike** results | the same |
| `lexical`, `exact`, `full-text`, `fuzzy`, `proximity` | not supported | — (`--leet-level` is an error) |

The setting is `auto` unless you change it: each engine uses its own default above, and
`off`, `basic`, `standard` or `extended` applies to every engine that can honour it.
`--leet-level off|basic|standard|extended` overrides it for one search; the results header
and exports record it. With look-alikes on, `like`'s `SearchMatch.score` is the share of
`content` matched as typed (a plain `password` before a `p@55w0rd`), and with
`--case-sensitive` a look-alike stands for the lower-case letter, so only that case
matches it.

`noise-fuzzy` finds `content`'s characters when they are hidden by stray characters,
look-alikes and typos together — the text is cleaned up in that order, and `content`
goes through the same steps, so it may itself be written with noise or look-alikes:

1. **Noise is ignored.** Whitespace and punctuation between the characters are
   skipped, as far as `--noise` allows. Letters and digits are never noise (a stray
   letter is a typo, below). `@ $ ! | + ( [ {` can be look-alikes, so they are read
   as letters first (an `@` that was really noise then costs one edit).
2. **Look-alikes are folded** to the letters they stand for — the single characters
   of `--leet-level` (default `vethuq settings search normalize leetspeak`, or `basic`);
   multi-character spellings like `|\|` are not folded.
3. **Typos are tolerated** like `fuzzy`: the rest must be within `--threshold` /
   `--fuzziness` of `content` (default `vethuq settings search fuzzy threshold`), at
   most 2 edits, and a `content` under 4 characters, or one still holding a digit
   after folding, must match exactly. Edits are insertions, deletions, substitutions
   and swaps of two neighbours; a case difference is one edit with
   `--case-sensitive`.

The words of `content` are matched as one run of characters, so `my password` finds
`m y p@55w0rd` (given enough noise). A match starts and ends at word edges, like
`fuzzy`'s — `hello` finds `ahello` as a close word, not `shellout` — but its
characters may be spread over several words (`he llo`). There is no minimum length.

`--noise low|medium|high` (default `low`, or `vethuq settings search noise-fuzzy
noise`) sets how much noise a match may skip: `low` at most 1 character in a row and
2 in all (`he llo`, `h.ello`, `h e llo`), `medium` 3 and 6 (`h..e llo`, `h e l l o`,
`h @ 3 l l 0`), `high` 6 and 12 (`h @ e # l l o`). Results are ordered by how clean
the match is (`SearchMatch.score` is 1.0 for the text as typed and falls with each
edit, look-alike and noise character); `--distance` is an error with it, and
`--noise` is an error with any other engine (the combined search applies it to its
`noise-fuzzy` run).

Pages come from the database's own index of each page's *skeleton* — its text without
noise and with look-alikes folded, recorded when the page is written and searched
through a trigram index (see `index rebuild-search`) — and from there only the stretches
of a page where `content` can lie are read, so it doesn't scan every page. A very short
`content` can't be narrowed that way and is searched through the whole skeleton.

`--case-sensitive` / `--no-case-sensitive` overrides
`vethuq settings search case-sensitive`, and only `like`, `lexical`, `fuzzy` and `noise-fuzzy` act on it
(for `fuzzy` a difference in case counts as one edit):
`exact` is always case-sensitive while `full-text` and `proximity` never are,
so asking for the opposite explicitly (`--engine exact --no-case-sensitive`,
`--engine full-text --case-sensitive`) is an error, while a stored
preference the engine can't honour is simply not applied. The header of
the results shows which engine (with its case-sensitivity, threshold or
distance) produced them, and an empty `exact`, `full-text`, `fuzzy`,
`proximity` or `noise-fuzzy` search suggests a looser search.
Results open in a pager, starting at the top: scroll (e.g. the
down arrow, space, or page down) to reveal more, press `h` (with the
default `all` engine) for what Exact, Contains, Relevant, Near, Word
and Similar mean, and press `q` to close it. Each file with a match prints its path once, followed by a
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

**`like`** finds the text anywhere, even inside a word:

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

**`noise-fuzzy`** finds text hidden by noise, look-alikes and typos together:

```bash
vethuq search hello --engine noise-fuzzy                    # "he llo", "h3ll0", "helo", "hallo"
vethuq search hello --engine noise-fuzzy --noise medium     # also "h..e llo", "h @ 3 l l 0"
vethuq search hello --engine noise-fuzzy --noise high       # also "h @ e # l l o"
vethuq search password --engine noise-fuzzy --fuzziness strict --leet-level standard
vethuq settings search noise-fuzzy noise set medium         # the default from now on
```

**Look-alikes** with `like` (they are on by default for `noise-fuzzy` and the combined search):

```bash
vethuq search cafe --engine like --normalize unicode=full    # finds "café" (and "cafe\u0301", "cafe")
vethuq search abc --normalize unicode=full,leetspeak=basic   # full-width ＡＢＣ, "4bc", ...
vethuq search hello --engine like --leet-level basic         # finds "hello", "h3ll0", "He11o"
vethuq search p@55w0rd --engine like --leet-level basic      # finds "password" and "p@55w0rd"
vethuq search hello --engine like --leet-level basic --case-sensitive   # "hello", "h3ll0" - not "H3LL0"
vethuq search game --engine like --leet-level standard       # "9ame" too (a 9 is a g from standard)
vethuq settings search normalize leetspeak set standard      # the default for every engine from now on
```

To make an engine, case, look-alikes, fuzzy threshold or proximity distance the
default for every search, see `vethuq settings search engine`, `case-sensitive`,
`normalize leetspeak`, `fuzzy threshold` and `proximity distance`
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

### `location backups show|set|reset`

Backups are kept in a `backups` folder next to the database by default. `set <folder>` moves the existing backups to another folder (for example another drive) and keeps new ones there; it shows what will move and asks first (`--force` skips the question). `show` prints the current folder and `reset` moves everything back to the default. The folder is remembered in the same small `location.json` file as `vethuq settings location set`.

```bash
vethuq settings location backups set D:\VethuQ-backups
vethuq settings location backups show
vethuq settings location backups reset
```

### `db backup`

Configure automatic database backups: `enable` (the default) or `disable`, how often they are taken (`interval`, in minutes — 1 day by default) and how long they are kept (`retention`, in days — 7 by default).

```bash
vethuq settings db backup set enable
vethuq settings db backup show
vethuq settings db backup interval set 720
vethuq settings db backup retention set 14
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
of `all` (the default — every engine, ranked together), `like`, `exact`,
`full-text`, `fuzzy`, `proximity` or `noise-fuzzy`.

```bash
vethuq settings search engine set full-text
vethuq settings search engine show
```

### `search case-sensitive enable|disable|show`

Configure whether `vethuq search` matches case by default. Disabled by
default. Only the `like`, `lexical`, `fuzzy` and `noise-fuzzy` engines act on it (it is the same setting as `normalize case` being `match`); `--case-sensitive` /
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

### `search normalize case set <value>|show`

Configure whether `vethuq search` treats upper and lower case as the same letter, when
`--case-sensitive` / `--no-case-sensitive` isn't given: `auto` (the default — each engine's
own: `like`, `lexical`, `fuzzy` and `noise-fuzzy` ignore case, `exact` always matches it,
`full-text` and `proximity` never do), `ignore` or `match` (for the engines that can honour
it). `case-sensitive enable|disable` above is the same setting as `match` / `ignore`.

```bash
vethuq settings search normalize case set match
vethuq settings search normalize case show
```

### `search normalize unicode set <value>|show`

Configure whether `vethuq search` treats characters that are written differently as the same,
when `--normalize unicode=...` isn't given: `auto` (the default — each engine's own: `basic` for
`like` and `exact`, `full` for `fuzzy` and `noise-fuzzy`), `off`, `basic` (compose characters, keep
accents) or `full` (also fold accents and compatibility forms: `cafe` finds `café`). Honoured by
`like`, `fuzzy` and `noise-fuzzy`; `exact` only when asked for in a search.

```bash
vethuq settings search normalize unicode set full
vethuq settings search normalize unicode show
```

### `search normalize leetspeak set <value>|show`

Configure whether `vethuq search` reads look-alike characters (`3` for `e`, `@` for `a`) as
the letters they stand for, when `--leet-level` isn't given: `auto` (the default — each
engine's own: `basic` for `noise-fuzzy` and the look-alike results of the combined search,
none for `like`), `off`, `basic` (`0` `1` `3` `4` `5` `7` `@` `$`), `standard` (also `2` `6`
`8` `9` `+` `!` `|`) or `extended` (also `(` `[` `{`). Each level includes the one before it.
The substitution table is built in and isn't user-editable. Honoured by `like` and
`noise-fuzzy`.

```bash
vethuq settings search normalize leetspeak set standard
vethuq settings search normalize leetspeak show
```

### `search noise-fuzzy noise set <level>|show`

Configure how much stray punctuation and whitespace `vethuq search --engine noise-fuzzy`
(and the Obscured results of the default combined search) skips inside a match, when
`--noise` isn't given: `low` (the default — at most 1 noise character in a row and 2 in
all), `medium` (3 and 6) or `high` (6 and 12). Letters and digits are never noise. The
engine also uses the fuzzy threshold and the leetspeak normalization settings.

```bash
vethuq settings search noise-fuzzy noise set medium
vethuq settings search noise-fuzzy noise show
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

### `purge <id-or-path> [--force]`

Permanently delete a source you've already removed, together with its
indexed data, without waiting for the retention period (see
`vethuq settings index removed-retention`). It also accepts the path of a
removed file inside a source. Asks for confirmation first unless `--force`
is given. A source or file that is still active is refused — run
`source remove` first. Every cleanup, manual or automatic after the retention
period, is recorded in the database log (`vethuq logs database`) with when it
ran, what was removed and how many records.

```bash
vethuq source purge 3
vethuq source purge ./path/to/folder-or-file --force
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
