# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `vethuq settings location set <folder>` moves VethuQ's database, logs and run files to a folder of your choice (asks first; `--force` skips the prompt); `location show` prints where they are (also under Settings > Location in the interactive menu). The `VETHUQ_HOME` environment variable overrides it.
- `vethuq search --engine lexical` finds your text anywhere in a page (mid-word included) and lists the best-matching pages first; it needs at least three characters. In the default combined search it appears as a "Relevant" label.
- `vethuq search` now runs every engine at once by default and lists each page once, ranked by how strictly it matched (Exact, Contains, Relevant, Near, Word, then Similar) and labelled with how it was found. Press `h` in the results pager for what each label means. Pick a single engine with `--engine`; `client.search.run_pages` returns the ranked pages.
- `vethuq source list <id-or-path>` lists the files under a source with their id and index status; add `--detail` for timestamps, OCR phases and more. Also in the interactive menu (Sources > List Files). `--export <file> [--format json|html]` writes any `source list` form (sources, files, or files with `--detail`) to a file, like `search --export`. Sort with `--sort asc|desc` and `--sort-by filename|id|status` (ascending by filename by default).
- `client.sources.files(path_or_id)` returns the files under a source with their status and detail.
- If the index worker crashes hard (for example inside the OCR library), the fault trace now lands in `index.log` and `index status` names the crash; deeper OCR passes also log each page and angle before reading it.
- Command output is now shown in full-width panels with left-aligned titles (and tables for lists): search results (one panel per file, one box per match), sources, index, stats, logs and settings.
- The interactive menu now opens with a VethuQ header panel and shows the main menu and every sub-menu as a panel of numbered options.
- `vethuq logs <component> --follow` now updates a single live panel with the newest entries instead of scrolling.
- `vethuq index history` shows start times in a friendly form ("Today, 14:40") in your local time.
- `--help` now explains each value for `vethuq search --engine`, `vethuq logs` (components, `--level`, `--export`) and the engine, format, threshold, distance, level and worker settings.
- `vethuq search --engine proximity` finds passages where all your words sit within a set number of words of each other; set how near with `--distance` or `vethuq settings search proximity distance`. Fuzzy thresholds can now be given as percentages (`80%`).
- `vethuq search --engine fuzzy` finds words close to yours, so typos and OCR misreads like `Muzeum` or `Museurn` still find `Museum`; set how close with `--threshold` or `--fuzziness strict|balanced|loose`, or store a default with `vethuq settings search fuzzy threshold`.
- `vethuq search` can now match exactly as typed (`--engine exact`) or by whole words with the best matches first (`--engine full-text`), and `--case-sensitive` makes the default search care about capitals; choose the defaults with `vethuq settings search engine` and `case-sensitive`.
- Logs no longer record what you searched for (`vethuq search` logs `<query omitted>`; a failed search logs only the query's length), and a test now fails the build if any log call references document text or search queries (`ocr_text`, `native_text`, `query`, ...).
- Logs now cover scanning and processing per area: `index.log` records each source scan (start, files found, outcome), duplicate skips, per-attempt retries, and OCR, native-extraction and indexing failures with file, page, engine and exception; `database.log` records database open/schema/write failures and search failures (with the query and engine).
- Logging now records shutdown as well as startup: `cli.log` gets a `Finished` line with the exit code and duration for every command, `ui.log` a `VethuQ UI stopped` line, and `index.log` marks each index worker's start and exit.
- `vethuq search` now tags each match with how its page's text was obtained (`[native]`, `[ocr]` or `[mixed]`).
- `vethuq search` now shows each result's file name as a bold heading above its full path.
- Search now returns every occurrence of a query within a page, not just the first.
- Each indexed page now records its text's character count; existing databases are updated automatically.
- Database access now goes through a storage interface, so the CLI, desktop app and Python library no longer handle raw database connections.
- Search now runs behind a `SearchEngine` interface, so engines can be selected or chained as fallbacks. Searches now find candidate pages through the FTS5 index, falling back to plain matching only for queries under three characters.
- `vethuq logs <database|index|ui|cli>` shows the latest log entries, with `--tail`, `--follow`, `--level`, `--date` and `--export`; it's also in the interactive menu and `client.logs.tail` in the Python library.
- VethuQ now writes separate daily log files for the database, indexing, desktop app and CLI. Choose how verbose they are and how many days are kept with `vethuq settings logs level|retention` (also `client.settings.logs` in the Python library).
- VethuQ's data folder is now organised into `db/`, `run/` and `logs/`; an existing database is moved into `db/` automatically.
- VethuQ now checks the database for corruption (once a day when it's opened, or on demand with `vethuq db integrity-check`) and logs the result; configure it with `vethuq settings db integrity-check`.
- OCR can now find rotated text. Files are still indexed quickly first so they're searchable right away, then deeper passes keep adding text in the background — choose how thorough with `vethuq settings ocr engine set quick|moderate|deep` (also in the interactive menu and `client.settings.ocr.engine`).
- Indexing now guards against files that are still being written or that change while being read: a file whose size/mtime isn't stable across two checks is skipped until the next scan, and one modified during processing has its result discarded and is retried (then marked as an error). `vethuq settings index stability-check set/show` (also `client.settings.index.stability_check`) controls the check interval (1 second by default, 0 disables it).
- VethuQ is now installable via `pip install vethuq` (CLI and Python library, Windows and Linux), and ships as a Windows desktop installer via GitHub Releases.
- The Windows desktop installer now also installs the `vethuq` CLI alongside the desktop app, with an option to add it to your PATH.
- The Python library now offers a `vethuq.Vethuq()` client with `client.sources` (add/list/remove), `client.index` (run/restart/status/stop/pause/resume/history), `client.settings` (GPU, search snippet/export format, and indexing retention/retry/workers/stale-lock), `client.stats` (processing/confidence statistics), and `client.search` (search indexed content and export results) — no database connection to manage yourself.
- `vethuq`'s interactive menu (run with no arguments) now includes Stats, matching the `vethuq stats` command.
- Initial repository scaffold: uv workspace, `vethuq-core` package, CI, and pre-commit setup.
- Users can add folders and files as sources for OCR/indexing, from both the CLI (`vethuq source add/list/remove`) and the desktop UI's Settings > Sources view, which also lets you delete a registered source.
- Registered sources are now OCR'd (English, PDF/PNG/JPEG) and indexed into the local database — via `vethuq index run` in the CLI, or automatically in the background in the desktop app.
- PDFs with real, selectable text are now indexed directly from that text instead of being run through OCR, which is faster and more accurate; OCR now only runs on scanned pages or scanned regions within an otherwise digital page.
- OCR can now optionally use the GPU (off by default) — toggle it with `vethuq settings gpu enable/disable`, or from the desktop app's Settings menu.
- The desktop app now shows a status bar with indexing progress while sources are being processed in the background.
- Indexed documents now record how long OCR took to process them, alongside their confidence score.
- `vethuq index run` now runs in the background and returns immediately. Use `vethuq index status` to check progress, `vethuq index pause`/`resume` to pause and continue a run, `vethuq index stop` to cancel it, and `vethuq index history` to see past runs. You can also target a specific source by id or path.
- `vethuq index restart` retries just the files that previously failed OCR, without redoing new or already-indexed files.
- The desktop app's background indexing now shares the same engine as `vethuq index run`, checking every 5 seconds for progress. Closing the app lets whatever file is currently being processed finish in the background rather than cutting it off.
- The desktop app's Sources view now lets you right-click a source to index it now, retry its failed files, or view its indexing history; Pause, Resume, and Stop buttons control the overall background run.
- `vethuq index history` can now be filtered to a specific source by id or path.
- You can now search indexed content from the CLI with `vethuq search <content>`, which highlights the match in a snippet of surrounding text; how much surrounding text is shown is configurable with `vethuq settings search snippet set/show`.
- The desktop app now has a search screen (a search box and a results list showing each match's file), and its toolbar has been redesigned as a ribbon with a Windows 11-styled look.
- Search results and Sources list columns can now be resized, and show hover tooltips for text that's cut off.
- The Home ribbon now has quick actions for adding a folder/file, viewing the source list, and pausing/stopping/deleting a selected source.
- The Sources list now shows a file/folder icon, capitalized status, and how many files have been processed per source.
- Viewing a source's run history now opens alongside the source list instead of a separate popup window.
- Dialogs and right-click menus in the desktop app are now styled to match its Windows 11 theme.
- A removed source is now fully deleted from the database (not just hidden) after it's been removed for a while — 7 days by default, configurable with `vethuq settings index removed-retention set/show`.
- Indexed documents now record their file size.
- VethuQ now refuses to open a database created by a newer version and tells you to upgrade, instead of risking damage to it.
- VethuQ now tracks running averages of OCR duration per file type, and confidence per file type and text-source (native/OCR/mixed), so a document type's confidence isn't blended across very different sources.
- `vethuq index status`'s ETA is now based on historical average OCR duration per file type, rather than this run's own pace, so it's available even before any file in the current run has finished.
- Files with identical content to one already indexed are now detected as duplicates and linked to the original instead of being OCR'd again; both the CLI and the desktop app flag duplicates in search results and index status.
- `vethuq index run` now also re-indexes files whose content has changed since they were last indexed, not just newly added ones; if a changed file was one others were flagged as duplicates of, one of them takes over as the original instead.
- `vethuq index run` now recognizes a file that's been renamed or moved within its source (by content, without re-running OCR), and flags a file that's gone missing from its source for cleanup after the same retention period used for removed sources.
- OCR results now record which engine and language processed them, the image resolution used, and memory/CPU usage during processing.
- A file that fails OCR is now automatically retried before being marked as failed — configurable with `vethuq settings index ocr-retry set/show` (3 attempts by default).
- The CLI's colored output now uses your system pager (e.g. `less`) to scroll through `vethuq search` results, instead of a custom built-in one.
- Running `vethuq` with no subcommand now opens an interactive menu for Search, Sources, Index, and Settings, instead of just printing help text.
- While viewing `search` results, pressing `e` now lets you export them to a file (asking for the filename and format) instead of having to re-run the search with `--export`.
- Background indexing can now process files with multiple worker threads instead of one at a time — configurable with `vethuq settings index thread-workers set/show` (also available from the interactive menu; disabled by default, set a fixed 1-8, or `auto` to keep it sized to current CPU/memory usage throughout the run). Pending files across all sources are now indexed in filename order together, rather than one whole source at a time.
- `vethuq stats show` displays accumulated OCR processing and confidence statistics, and `vethuq stats reset` (with confirmation, or `--force`) clears them for a fresh baseline.
- If VethuQ is closed abruptly (e.g. a crash or power loss) mid-indexing, the next run now recovers on its own instead of needing `--force` — configurable with `vethuq settings index stale-lock set/show` (auto-recovers by default).
- Each indexed document now has a stable logical identity, independent of its file path, so duplicate copies of the same content can be tracked as one document behind the scenes rather than only ever chaining to a specific file row.
- Indexed documents now also record OS-level file creation/modification timestamps captured at scan time, alongside their content hash; the hash column is now named `sha256` for what it's always held.
- A document actively being OCR'd now shows a distinct `processing` status instead of staying `pending` for the whole run.
- Two overlapping index runs can no longer process the same file at once, and a file left mid-processing by a crashed or force-stopped run is now retried automatically.
- OCR now detects and corrects rotated pages and rotated text lines (e.g. scanned or photographed documents that aren't perfectly upright), instead of assuming every page is already correctly oriented.
- The test suite now runs in parallel and covers real PDF, PNG and JPEG sample files and the `vethuq` Python package.
- The database now survives a crash mid-write and no longer fails with "database is locked" when indexing and a CLI command overlap; a schema upgrade first backs up the database to `vethuq.db.bkp`.
- Identical copies of a file are now recognised as one document, and OCR progress is tracked per document rather than per file copy.
- Searching is now faster on large libraries, and still matches text anywhere within a word, case-insensitively.
- Indexing now reports why a file couldn't be read — removed mid-run, password-protected, or corrupted — instead of a generic failure, and doesn't retry it.
- Files VethuQ can't read, such as `.txt` or `.csv`, are now listed as "Unsupported file format" instead of being silently ignored.

### Changed

- OCR settings now live under their own group: `vethuq settings index ocr-retry` is now `vethuq settings ocr retry`, and `settings index engine` is now `settings ocr engine` (likewise `client.settings.ocr.retry` / `client.settings.ocr.engine`, and Settings > Ocr in the interactive menu).

### Fixed

- `vethuq index status` no longer shows a run as "running" after its worker has died: it now reports it as failed with the reason, and flags a worker that has stopped responding.
- A file edited while an index run was already working through it now gets its quick re-scan first, instead of waiting behind the moderate/deep passes.
- Re-indexing a document (e.g. after removing and re-adding its source) no longer leaves stale page text from the previous run alongside the new results.
- `vethuq index run` now also checks already-indexed sources for files added since the last run, instead of only ever looking at sources it hasn't touched yet.
- Commands that don't do OCR (e.g. `vethuq settings gpu status`) no longer print unrelated OCR-engine startup messages.
- Searching no longer returns matches from files whose source has been removed.
- Permanently purging removed sources no longer fails with a database error when two of them shared duplicate-flagged content, and no longer leaves `index history` pointing at a source that's gone.
- A document's indexed result is now saved all-or-nothing, so a failure partway through can no longer leave it marked `indexed` with missing pages or metrics.
