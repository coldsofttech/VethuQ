# CLI reference

The `vethuq` command-line tool manages sources (files/folders registered
for OCR/indexing), runs the OCR indexing pipeline, and configures
settings.

## `vethuq source`

### `vethuq source add <path>`

Register a file or folder as a source. Folders are indexed recursively.
Prints a hint to run `vethuq index run` once added — adding a source
does not index it automatically.

```
vethuq source add ./path/to/folder-or-file
```

### `vethuq source list`

List all registered (active) sources, most recently added first, with
their id, type (`file`/`folder`), and status (`pending`/`indexed`/`error`).

```
vethuq source list
```

### `vethuq source remove <id-or-path>`

Remove a registered source (soft-delete — the source stops being
processed but its history isn't erased). Accepts either the source's id
(from `source list`) or its path.

```
vethuq source remove 3
vethuq source remove ./path/to/folder-or-file
```

## `vethuq index`

### `vethuq index run [source] [--wait] [--force]`

Start OCR indexing as a background process and return immediately. A
freshly added/reactivated (`pending`) source is (re)processed in full; an
already-`indexed`/`error` source is checked for files added since the
last run, and only those new (or previously failed) files are processed
— already-indexed files are left untouched. Extracts text (English; PDF,
PNG, and JPEG files supported) and stores it locally. PDF pages with a
real text layer are read directly from it; OCR only runs on scanned
pages/regions.

Pass a source id or path to index only that source; omit it to index
every active source. `--wait` blocks until the run finishes, printing
progress as it goes, instead of returning immediately. `--force` clears
a lock left behind by a previous run that didn't exit cleanly (e.g. after
a crash) — without it, `run` refuses to start a second run on top of one
that might still be alive.

```
vethuq index run
vethuq index run ./path/to/folder-or-file
vethuq index run 3 --wait
vethuq index run --force
```

### `vethuq index restart [source] [--wait] [--force]`

Retry only files that previously failed OCR, as a background process.
Unlike `run`, new files and already-indexed files are left untouched —
only files whose last attempt errored are (re)processed. Takes the same
`source`/`--wait`/`--force` options as `run`.

```
vethuq index restart
vethuq index restart ./path/to/folder-or-file
```

### `vethuq index status [source] [--json]`

Without a source, shows the current (or most recently finished)
background run: status, progress (`processed/total`), failed-file count,
the file currently being processed, and an ETA while running. With a
source id or path, shows a detailed per-file breakdown for that source
instead (status, confidence, and duration for each file). `--json`
prints machine-readable output.

```
vethuq index status
vethuq index status ./path/to/folder-or-file
vethuq index status 3 --json
```

### `vethuq index pause` / `vethuq index resume`

Pause or resume the currently running background index. Pausing takes
effect after the file currently being processed finishes; the run stays
alive, waiting to be resumed.

```
vethuq index pause
vethuq index resume
```

### `vethuq index stop`

Stop the currently running background index. Requests a graceful stop
first and force-terminates the process if it doesn't exit promptly.

```
vethuq index stop
```

### `vethuq index history [--limit N] [--json]`

List past background index runs (target, status, files
processed/failed, start/end time), most recent first. `--limit` caps how
many are shown (default 10).

```
vethuq index history
vethuq index history --limit 25 --json
```

## `vethuq settings`

### `vethuq settings gpu enable|disable|status`

Configure whether OCR should attempt to use the GPU. Disabled by
default. Enabling it only has an effect if a CUDA-capable PaddlePaddle
build with a visible GPU is actually installed — otherwise OCR silently
falls back to CPU.

```
vethuq settings gpu enable
vethuq settings gpu disable
vethuq settings gpu status
```
