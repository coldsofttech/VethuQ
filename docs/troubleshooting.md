# Troubleshooting

When VethuQ can't start or can't carry on, it stops with a plain message that says what is
wrong and what to do, exits with a non-zero code, and writes the same message to the log
(`vethuq logs cli`, or `vethuq logs index` for indexing).

```
Error: The VethuQ database at C:\...\vethuq.db is damaged or isn't a database (...).
What to do: Restore a backup with 'vethuq db restore <name>' ...
```

Each kind of problem has its own exit code, so scripts can tell them apart.

| Exit code | Problem | Section |
|---|---|---|
| 10 | Invalid settings | [Invalid settings](#invalid-settings-exit-code-10) |
| 11 | Data folder not writable | [Data folder not writable](#data-folder-not-writable-exit-code-11) |
| 12 | Damaged database | [Damaged database](#damaged-database-exit-code-12) |
| 13 | OCR engine or models missing | [OCR engine or models missing](#ocr-engine-or-models-missing-exit-code-13) |
| 14 | Database from a newer version | [Database from a newer version](#database-from-a-newer-version-exit-code-14) |
| 15 | Leftover index lock | [Leftover index lock](#leftover-index-lock-exit-code-15) |

In Python, the same problems are raised as exceptions that all derive from
`vethuq.StartupError`; see [PYTHON_API.md](PYTHON_API.md#errors).

## Invalid settings (exit code 10)

**What you see:** "The settings file … can't be read" or "is not in the expected format", or
"`VETHUQ_HOME` points to …, which is a file, not a folder".

**Why:** the small settings file that remembers where your data lives (written by
`vethuq settings location set`) has been edited or damaged, or the `VETHUQ_HOME` environment
variable points somewhere that isn't a folder.

**Fix:**
- Open the file named in the message and repair it, or delete it. Deleting it sends VethuQ
  back to its default data location; your data is not removed.
- If `VETHUQ_HOME` is set, point it at a folder or unset it.

## Data folder not writable (exit code 11)

**What you see:** "VethuQ can't write to its data folder …".

**Why:** VethuQ couldn't create the folder or write a file in it - usually permissions, a
read-only or full disk, or a drive that is no longer connected.

**Fix:**
- Check the folder named in the message: that it exists, is writable and the disk has free
  space.
- Or choose another location with `vethuq settings location set <folder>`, or set
  `VETHUQ_HOME`.

## Damaged database (exit code 12)

**What you see:** "The VethuQ database at … is damaged or isn't a database", or, after an
interrupted indexing run, "The database failed its integrity check".

**Why:** the database file was corrupted (for example by a crash, a full disk or a sync tool)
or is not a VethuQ database.

**Fix, from least to most drastic:**
1. `vethuq db integrity-check` to see what is wrong, then `vethuq db repair`.
2. `vethuq db backup list`, then `vethuq db restore <name>` to go back to a backup.
3. `vethuq db reset` clears everything and starts fresh. Use it as a last resort.

If the file is not a database at all, move it aside and VethuQ will create a new one.

## OCR engine or models missing (exit code 13)

**What you see:** "The OCR engine (PaddleOCR) isn't installed", or "The OCR models couldn't be
loaded".

**Why:** the OCR engine is not installed, or its model files haven't been downloaded yet and
could not be fetched.

**Fix:**
- Reinstall VethuQ (`pip install --force-reinstall vethuq`).
- Connect to the internet once so the models can download, then run indexing again.

This is checked when you start indexing (`vethuq index run` / `restart`), and is not needed for
searching or managing sources.

## Database from a newer version (exit code 14)

**What you see:** "The database schema (version N) is newer than this version of VethuQ
supports".

**Why:** the database was opened by a newer VethuQ, and an older one can't safely use it.

**Fix:** upgrade VethuQ (`pip install --upgrade vethuq`). Don't delete the database.

## Leftover index lock (exit code 15)

**What you see:** "Found a lock left behind by a run that didn't exit cleanly".

**Why:** an earlier indexing run stopped without cleaning up after itself.

**Fix:**
- `vethuq index run --force` clears the lock and starts a new run.
- `vethuq settings index stale-lock set enable` makes VethuQ clear it automatically next time.
