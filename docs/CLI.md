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

### `vethuq index run`

Run OCR indexing across every active source. A freshly added/reactivated
(`pending`) source is (re)processed in full; an already-`indexed`/`error`
source is checked for files added since the last run, and only those new
(or previously failed) files are processed — already-indexed files are
left untouched. Extracts text (English; PDF, PNG, and JPEG files
supported) and stores it locally. PDF pages with a real text layer are
read directly from it; OCR only runs on scanned pages/regions. Prints
per-file status and confidence (`indexed | confidence: NN%`, or
`error | <message>`).

```
vethuq index run
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
