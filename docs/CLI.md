# CLI reference

The `vethuq` command-line tool manages sources (files/folders registered
for OCR/indexing) and runs the OCR indexing pipeline.

## `vethuq source add <path>`

Register a file or folder as a source. Folders are indexed recursively.
Prints a hint to run `vethuq index run` once added — adding a source
does not index it automatically.

```
vethuq source add ./path/to/folder-or-file
```

## `vethuq source list`

List all registered (active) sources, most recently added first, with
their id, type (`file`/`folder`), and status (`pending`/`indexed`/`error`).

```
vethuq source list
```

## `vethuq source remove <id-or-path>`

Remove a registered source (soft-delete — the source stops being
processed but its history isn't erased). Accepts either the source's id
(from `source list`) or its path.

```
vethuq source remove 3
vethuq source remove ./path/to/folder-or-file
```

## `vethuq index run`

Run OCR indexing on every source that is still `pending`. Extracts text
(English; PDF, PNG, and JPEG files supported) and stores it locally.
Prints per-source progress and the resulting status (`indexed`/`error`).

```
vethuq index run
```
