# Changelog

All notable changes to the `VethuQ` package are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions come from git tags named
`vethuq-vX.Y.Z` (through hatch-vcs), not from this file; until the first tag, the version is `0.1.0`.

## [Unreleased]

### Changed (languages, file types and tiers)
- Asking for a language, file type or tier VethuQ doesn't know now raises an error, instead of returning nothing.
- File types can be switched off and on (`file_types.disable` and `enable`); files of a switched-off type are no longer read. `file_types.list()` is now `list_all()`, with `list_enabled()` and `defaults()` added.
- `tiers.use()` is now `tiers.set()`, `TierInfo` is `Tier` and `VersionDetails` is `Version`.
- `client.version` lists the file types, search engines, OCR engines, OCR languages and add-ons that are installed.
- Errors are the public ones in `vethuq.errors`; the language, file type and tier errors have their own modules.

### Added (NDJSON files)
- The `.ndjson` and `.jsonl` (JSON Lines) file types, as the licensed add-on `vethuq-addon-ndjson` (not installed with VethuQ: `pip install vethuq-addon-ndjson`, then `Ndjson(client).set_licence(token)`). Each line is flattened to `path: value` lines like a JSON file, records are separated by a blank line, a line that is not valid JSON is left out and counted, and the file is read a line at a time. It keeps `encoding`, `record_count`, `invalid_line_count`, `value_count`, `max_depth` and `truncated` in the `ndjson_pages` table. The web interface previews the file as it is on disk, coloured like JSON.

### Added (Parquet files)
- The `.parquet` and `.pq` file types, as the licensed add-on `vethuq-addon-parquet` (not installed with VethuQ: `pip install vethuq-addon-parquet`, then `Parquet(client).set_licence(token)`). The table is indexed as text (the column names, then a line per row), never OCR'd. It keeps `row_count`, `column_count`, `row_group_count` and `indexed_row_count` in the `parquet_pages` table. A search match in a Parquet file carries `line` (the first line is the column names, then the Nth row with something in it) and `column`, as for CSV, and the web UI shows the file as a table.

### Added (TSV files)
- The `.tsv` file type, as the free add-on `vethuq-addon-tsv` (not installed with VethuQ: `pip install vethuq[tsv]`). Read like CSV: a line per non-empty row, cells joined by " | ", never OCR'd. It keeps `encoding`, `row_count` and `column_count` in the `tsv_pages` table, and a search match in a TSV file carries `line` (the Nth non-empty row) and `column`, as for CSV.

### Added (where on a picture a match is)
- A page read by OCR keeps where each line was read (`pdf_line_boxes`, from the engine's `OcrResult.boxes`), and a search match carries `boxes`: the box of each line it covers on the picture, narrowed to the words' share of the line (near, not exact). Kept for the first read of a scanned page and for the lines a language pass or a deeper phase adds at the upright angle; a page read again has its boxes replaced. None for a page with a text layer, and for an engine that does not say where.

### Added (text of a page)
- `search.page_text(document_id, page_number=1)` returns the text stored for a page (`PageText`), as searches saw it: for a text file, the file's text, which a match's `line` and `column` count in (a Markdown file's is its words without the markup).

### Added (where a match sits)
- A search match carries `line` and `column` for text and CSV files (for CSV the Nth non-empty row, and a column in its indexed text), so an application can open the file at the match. PDF matches already have `page_number`.

### Added (searching within file types and sources)
- `search.run(file_types=..., sources=...)` keeps matches of files read as those types (ids of `client.file_types`)
  and of those sources, in the total and the paging too; a match carries its `file_type`. CLI: `search --file-type
  pdf --source 2`.

### Added (turning add-ons off)
- `addons.set_enabled(id, enabled)` turns an installed add-on off or on; it applies at the next start. An add-on
  that is off is listed as `AddonStatus.DISABLED` (and `AddonInfo.disabled` says what is saved); `english` can't
  be turned off. CLI: `addons enable` and `addons disable`.

### Changed (the grace is internal)
- The grace allowance is no longer shown anywhere: `CreditBalance` has no `grace` and its `total` is daily,
  promotional and one-off credits only; `credits.grants()` no longer lists it (`kind="grace"` is refused), and
  pages it paid for are left out of `history()` and `usage()`. The wallet still spends it, so a run is not
  stopped the moment the credits run out. `CreditEstimate.affordable` is unchanged.

### Added (credits: grants and usage)
- `credits.grants()` lists every grant of credits (daily allowances, promotions by name, one-off starter and
  licence bundles) with what was used and what is left; `credits.usage()` totals what was spent by day, source
  or file (charges less refunds); a ledger entry names its `file`. A refund's note now ends with the file it
  was for ("<why>: <path>"). CLI: `credits grants` and `credits usage`.

### Added (HTML export filters and any-listing export)
- HTML exports have a filter bar (a dropdown of checkboxes per facet, "Showing X of Y", clear, striped rows that
  survive filtering): search results by match type, file type, language, text origin and folder; sources by type
  and status; a source's files by type, status and duplicate. Each table of a report filters on its own.
- `client.export` (`vethuq.export`): `records()` writes any listing to JSON or HTML and `sections()` several tables
  to one page; `ExportSection`. New templates `section.html` and `sections_export.html`; `list_export.html` has the
  script and the filter slot.

### Added (search pack)
- `vethuq[search]`: the search pack bundle (`vethuq-bundle-search`), which installs every search
  engine and normalizer.

### Changed (default search engines)
- VethuQ installs only the `like`, `exact` and `full-text` search engines (with the `case` and `unicode`
  normalisers). `lexical`, `proximity`, `fuzzy` and `noise-fuzzy` are now the extras `vethuq[lexical]`,
  `vethuq[proximity]`, `vethuq[fuzzy]` and `vethuq[noise-fuzzy]`; `fuzzy` and `noise-fuzzy` bring `leetspeak`.

### Added (index queue)
- `index.queue`: `submit`, `list`, `get`, `cancel`, `claim_next`, `run_next`, `finish`, `reconcile`, `wait`, and the
  service marker (`announce_service`, `clear_service`, `service_running`); `IndexJob`, `IndexJobStatus`,
  `IndexJobNotFoundError`, `IndexJobStateError`; `IndexStatus.queued_jobs`. The `index_jobs` table.

### Added (command line support)
- `client.addons.cli()`: the command groups installed add-ons describe (`Addon.cli()`, add-on API 0.11.0).
- `DocumentReader.may_ocr` (add-on API): a run of files whose readers never OCR in the quick phase no longer
  fetches the OCR models first (a text-only run used to wait on the download).

### Added (run health)
- A run's heartbeat: `IndexStatus.heartbeat_at` and `IndexStatus.stalled` (alive but quiet for two minutes).
- A full integrity check before a run that follows a left-behind one; `errors.DatabaseIntegrityError`.
- `search.rebuild()` refuses while a run is going and returns a `SearchIndexRebuildResult` (it returned the page
  count).

### Added (office file types)
- Tables for the Word, Excel, PowerPoint, RTF and email file types (`docx_pages`, `doc_pages`, `xlsx_pages`,
  `xls_pages`, `pptx_pages`, `ppt_pages`, `rtf_pages`, `eml_pages`); `vethuq[office]` installs the licensed office pack.

### Added (YAML)
- `yaml_pages` table for the YAML file type; `vethuq[developer]` installs the licensed developer pack.

### Added (web file types)
- Tables for the HTML, XML, CSS, JavaScript and JSON file types (`html_pages`, `xml_pages`, `css_pages`,
  `js_pages`, `json_pages`), filled from `ReadPage.details`; `vethuq[web]` installs the licensed web pack.

### Added (formatting)
- `vethuq.formatting.Formatting`: sizes, durations and timestamps for front ends; exports use it for file sizes.

### Added (settings)
- `settings.search.get_option/set_option/reset_option(engine, name)`: saved defaults for any engine's
  declared options (fuzzy threshold, semantic limit, proximity distance, ...), applied to a search
  unless its own `options=` says otherwise.
- `settings.ocr.get_gpu/set_gpu/reset_gpu`: ask OCR engines for the GPU (off by default); an engine
  that can't use it reads on the CPU.
- `settings.index.get_stale_lock/set_stale_lock/reset_stale_lock` (`auto`, `enable`, `disable`) and
  `index.clear_stale()`.

### Added (adaptive workers)
- With `workers` set to `auto`, an add-on that provides a worker scheduler (`Addon.worker_scheduler()`,
  add-on API 0.10.0) sets how many files are read at once while a run goes: a gate in front of the
  workers for the first read, the language passes and the deeper phases. One file always runs, a
  failing scheduler means the static estimate, and a fixed number of workers is never changed.
- `file_footprints` table: size, pages, seconds and files at once for each file read (no names or
  paths), the history the scheduler plans from. The newest 500 are kept.

### Added (controlling and repeating runs)
- `index.pause()`, `resume()` and `stop(wait=True)`: the request is kept on the run's row and the
  workers look at it between files, pages and angle passes, so it works from another thread or
  process. A stopped run ends as `STOPPED` and its file waits with the pages it has.
- `index.restart()` (failed files), `index.reindex(target)` and `index.reindex_file(file)` (read
  again; old pages stay searchable until replaced; a failed re-read keeps them). `IndexRun.mode`.
- `IndexStatus` adds `paused`, `stopping`, `phase`, `current_files`, `workers_active`,
  `deepened_pages` and `unsupported_files`. Errors `IndexNotRunningError` and `FileNotTrackedError`.
- Languages: `languages=` on every run method; with several candidates the first language's read is
  judged (confidence and script) and the others are queued as passes if it was unsure; a file with
  a text layer is tagged with the languages its text is in; rotated reads of a page in another
  language keep only lines in that language's script.
- The OCR models for each source's first language are fetched before the first file is read; a
  failed download is remembered for 30 seconds and said once.

### Added (OCR phases)
- The moderate and deep OCR phases (`vethuq-addon-ocr-moderate`, `-deep`): pages that needed OCR are
  read again at 90/180/270 degrees, then at every other multiple of 15, with the server models, and
  what is found is merged into the text. `settings.ocr.get/set/reset_engine` (`quick`, `moderate`,
  `deep`) says how far a run goes; `index.run()` does quick, then moderate, then deep, and returns to
  quick for files that appear or change meanwhile. Credits: rotated reads at the rotated rate.
  Remote tiers (GitHub, hybrid) take the deeper reads too. `pdf_pages_phases` records each read.
- Add-on API 0.9.0: `OcrRequest.angle`, `OcrEngine.recognize(image, angle=0)`, `ReadPage.region_phase`.
- A Markdown file's linked pictures are read from the moderate phase (quick leaves them).
- The quick phase stays installed with VethuQ; moderate and deep are optional installs:
  `pip install vethuq[deep-scan]` (the `vethuq-bundle-deep-scan` bundle) adds them.
- The ETA counts the deeper phases (`IndexEta.by_phase`); the quick pace no longer blends in the
  rotated reads.

### Added (progress and ETA)
- `client.index.status(wait=False, timeout=None)`: the latest run's counts, whether it is going, the
  remote jobs still out and an `IndexEta`; `wait=True` blocks until the run and its remote jobs are
  done (collecting results as they arrive). `IndexRun.eta` is set on what `run()` returns.
- The ETA is worked out from history: seconds per OCR page by file type (`usage_daily`, last 30 days,
  else all time), pages per file and the share needing OCR, and the time the remote tier's jobs took.
  `IndexEta.complete` says whether every part had history.

### Added (image file types)
- The image file types are free add-ons that are not installed with VethuQ: `vethuq-addon-png`,
  `-jpg` and `-tiff`. `pip install vethuq[images]` (or `vethuq-bundle-image`) installs the three.
- `client.version.bundles` lists the installed bundles (the `vethuq.bundles` entry point group).
- A picture a Markdown file links to is rendered by the add-on that reads its format, as an image
  file of its own would be (orientation, colour and size handled). The file is charged as one mixed
  page; the picture is not priced by its pixels.

### Added (file types)
- The `.txt`, `.csv` and `.md`/`.markdown` file types, as the free add-ons `vethuq-addon-txt`,
  `vethuq-addon-csv` and `vethuq-addon-markdown`, installed with VethuQ. These files are read
  straight from disk as one page of text each; they are never OCR'd and cost no credits.
- Add-on API 0.8.0: `ReadPage.ocr` (a page whose text is final however short is never OCR'd whole),
  `ReadPage.region_files` (the image file a region comes from) and `ReadPage.details`.
- Each text file type keeps what it knows about a page in a table of its own beside the text in
  `pdf_pages`: `txt_pages` (encoding), `csv_pages` (encoding, delimiter, row and column counts) and
  `markdown_pages` (encoding, number of linked pictures).
- A Markdown file's linked pictures are read with OCR when an installed add-on reads their format.
  Without one (the image pack is to come) the picture is skipped with a warning in the
  `vethuq.indexing` log and the text is indexed anyway.

### Added (export)
- `client.search.export(result, path, format=None)`, `client.sources.export(sources, path, format=None)`
  and `client.sources.export_files(source, files, path, format=None)`: JSON or one portable HTML
  page (logo, summary, palette in light and dark, printable). A search export records how the search
  ran (engine, normalizer levels, engine options, pages not prepared) and how each match was found
  (the engine's badge). `settings.search.get/set/reset_export_format`, `ExportFormat`.
- `SearchResult.options`: the engine options a search ran with.
- Add-on API 0.7.0: `LanguageSpec.script_ranges` (text is recognised as a language by its script;
  non-default-language runs in an HTML export are tagged `<span lang>`) and
  `SearchEngineSpec.badge`.

### Added (search engines)
- The engines `lexical`, `proximity`, `full-text`, `fuzzy`, `noise-fuzzy` and `semantic`, and the
  `leetspeak` normalizer, are add-ons (the first five and the normalizer are free and installed
  with VethuQ; `semantic` is `pip install vethuq[semantic]`). Add-on API 0.6.0.
- Engine options: `search.run(options=...)` (`"fuzzy.threshold=0.7"`), declared by each engine
  (`SearchEngineInfo.options`); `SearchOptionError` for an unknown option or a bad value.
- Optional normalizers: `like` and `fuzzy` take `leetspeak` when that add-on is installed and work
  without it.
- Ranking in VethuQ: `sort="rank"`, and in the `all` search hits of different engines that overlap
  are one match (the strictest engine's, listing every engine in `matched_by`).
- `engine="hybrid"` (`combine=`): `semantic` and a keyword engine, pages ranked by reciprocal rank
  fusion; settable as the default engine.
- `search.sync()` prepares pages for engines that need it (semantic embeds them), with progress and
  a `SearchSyncReport`; `SearchResult.pending` counts the pages an engine could not search yet.
- Add-on credits: `Host.credits` (rate card price, balance, charge) over a sub-wallet named after
  the add-on, `client.credits.wallets()` lists them, and the policy's `wallets.addons.<id>` and
  `rate_card.semantic` apply. Semantic search is free to use and costs about 0.5 credit a page to
  prepare, from the `semantic` wallet (50 credits a day by default).
- `Host.data_dir()`: a folder of an add-on's own (`<data root>/addons/<id>`, moved with the data).

### Changed
- `SearchSortBy` has `RANK`; `search.run(sort=...)` defaults to `path`, and to `rank` for `hybrid`.

### Added
- Package `VethuQ` (import name `vethuq`), versioned from git tags, exposing `APP_NAME`,
  `APP_TAGLINE`, `APP_VERSION` and `__version__`.
- `vethuq.VethuQ` client, the entry point to every feature below. It connects to the database on
  first use and can be used as a context manager.
- **Sources** (`client.sources`, types in `vethuq.sources`): `create`, `get`, `list` (filter by
  status, type and language; sort by field and order; include removed), `list_files`,
  `set_languages`, `remove`, `purge` and `purge_expired`. Results are `Source`, `SourceFile` and
  `PurgeResult`, with `to_dict()` and `to_json()`. `SourceType`, `SourceStatus`, `SourceSortBy` and
  `SortOrder` enums.
- **Document index** (internal `documents` and `document_index` tables): which files a source
  holds and where each is in indexing, by absolute path. `sources.list_files(id, detailed=True)`
  adds a `FileIndex` to each file (`FileStatus`: pending, processing, indexed, error, modified,
  removed, unsupported; sha256; the original of a duplicate) and also lists indexed files that
  have gone from disk until the source is purged. `status=` filters. Only PDF is supported for
  now. Reading never changes anything.
- **Source progress**: a source's `status` is now overall (`SourceStatus`: pending, in_progress,
  completed, error, removed), with `files_processed`, `files_total` and a `progress` text.
- Sources can't overlap: `create` raises `SourceOverlapError` for a path inside an active source or
  one that contains it. Purging a source deletes the record of its files.
- **Languages** (`client.languages`): languages come from language add-ons (add-on API 0.2.0,
  `Addon.languages()`); English is the free `vethuq-addon-english`, the system default, installed
  with VethuQ. `list_all`, `list_enabled`, `get`, `default`, `enable` and `disable`. A language is
  used when it is available (add-on installed and, if licensed, licensed) and enabled; disabling
  one saves the credits it costs, and at least one must stay in use (`LastLanguageError`). A
  disabled or unavailable language is refused for sources (`LanguageUnavailableError`). The
  `source_languages` table links sources to the languages they are read in.
- **Language settings** (`client.settings.languages`): the languages a source with none of its own
  is read in; English unless changed.
- **Settings** (`client.settings`): source retention for removed sources (7 days by default), log
  level and retention (`LogLevel`, 15 days by default), and update-check settings
  (`UpdateCheckMode`, snooze and skip). Changes to the log settings apply at once.
- **Indexing** (`client.index`, types in `vethuq.index`): `run(target=None, workers=None)`
  indexes every source, one source, or one file in a source, and returns an `IndexRun`; `get` and
  `history` (filter by target, status and time; sort; page). Native text first, then OCR: native
  pages need none, mixed pages read only their images, scanned pages are read whole. Files with
  the same content share their pages; a document read in a new language is merged. Failed files are
  retried and picked up again by later runs, password-protected files are `UNSUPPORTED`, and a run
  whose process died is failed at the next run. `IndexRunStatus`, `IndexRunSortBy`,
  `IndexAlreadyRunningError` and `IndexRunNotFoundError`. Purging a source deletes its runs.
- **Index settings** (`client.settings.index`): workers (`auto` or 0 to 8), retry attempts (3) and
  the stability check (1 second).
- **File types** (`client.file_types`), from add-ons (add-on API 0.3.0); PDF is `vethuq-addon-pdf`
  (pypdfium2). `list_files(detailed=True)` now also shows each file's pages, confidence, languages
  and file type.
- **OCR** (`client.ocr`): `engines`, `phases` and `models` (list, download, redownload, clear,
  clean). The engine is `vethuq-addon-paddle` (PaddleOCR, models in `<data root>/models`) and the
  phase `vethuq-addon-ocr-quick` (mobile models, upright pages). These three add-ons are free and
  installed with VethuQ.
- **Credits** (`client.credits`, types in `vethuq.credits`): the local wallet (500 a day, a 2,000
  starter, 2% free grace, no rollover), priced by page size from the signed policy's rate card with
  built-in defaults; `balance`, `next_reset`, `estimate`, `history` (filter, sort, page), `redeem` and
  `redeem_licence` (licence credit grants, once each). Pages are paid for as they are read and a
  file that fails is refunded; native pages, duplicates and unchanged files are free. When credits
  run out the run ends as `IndexRunStatus.WAITING_CREDITS` and continues after the reset. A policy
  change applies from the next UTC day. Errors `CreditsError`, `InvalidGrantError`,
  `CreditsExhaustedError`; `IndexRun` gains `pages_processed`, `ocr_pages` and `credits_charged`.
- **Statistics** (`client.stats`, types in `vethuq.stats`): `overview` (group by source, language,
  file type, engine, page source, confidence band or day; filter; sort; page), `source`, `failures`
  and `low_confidence_pages`, from daily totals that outlive files and purged sources.
  **Confidence bands** (`settings.confidence`; high from 90%, medium 80%, low 70%, below that
  unreliable); `list_files(detailed=True)` shows `band` and `low_confidence_pages` and filters by
  `min_confidence` and `band`.
- **Metrics sharing** (`client.metrics`, off by default): `status`, `opt_in`, `opt_out`, `preview`,
  `send` and `delete_data`. A content-free batch of the daily totals goes to the policy's collector
  at the end of an index run, at most once a day; sharing earns +10% daily credits. The batch
  schema and the collector (a Cloudflare Worker with D1) are in `metrics/`.
- **Processing tiers** (`client.tiers`, types in `vethuq.tiers`): where pages that need OCR are
  read. `local` (the default, on this computer), `github` (the GitHub add-on) and `hybrid`;
  `list`, `get`, `current`, `use` and `reset`. Tiers come from add-ons
  (`Addon.processing_tiers()`, add-on API 0.4.0) as an `OcrExecutor`; local OCR now runs through
  one. `index.run(tier=, wait=, timeout=)`, `IndexRun.tier` and the run status `WAITING_REMOTE`
  (remote tiers can't run yet). `TierError` and `TierUnavailableError`.
- **Pages are saved one at a time**: a page is saved (and its credits charged and counted) the
  moment it is read, so a file that stops part way (no credits, a failure, a crash) keeps its
  pages and the next attempt, in the same run or a later one, carries on after the last saved
  page without paying for them again. A page whose OCR is still to come is saved `waiting`.
- **Remote jobs** (`client.index.jobs()`, `client.index.collect()`, `RemoteJob`,
  `RemoteJobStatus`): a tier that works in batches gets the images of pages that need OCR, paid
  for when staged, in jobs bounded by `settings.tiers`; the run ends `WAITING_REMOTE` unless
  `wait=True`. Finished jobs are imported (files become indexed once all their pages arrive);
  failed, expired or empty results are refunded and their pages sent again later. Internal
  tables `remote_jobs` and `remote_job_pages`; `pdf_pages` gains a `status`.
- **Tier settings** (`client.settings.tiers`): hybrid size rule and phases, wait timeout and remote
  job limits.
- **Wallets by tier**: `credits.wallets()`, `credits.balance(wallet)`, `history(wallet=)`; the
  GitHub wallet (20 a day for a private runner repository, 200 for a public one), with promotions
  and the metrics bonus. `CreditBalance` and `CreditEntry` carry their wallet.
- **Search** (`client.search`, types in `vethuq.search`): `run`, `engines`, `normalizers`, `status`
  and `rebuild`. Engines and normalizers are free add-ons installed with VethuQ (`like`, `exact`,
  `case`, `unicode`). A search folds the query and each page alike with the normalizers that apply
  (levels from the search, the engine, your saved setting, or the engine's default), merges what
  engines agree on in the `all` search and shows the original text. An index of each page's coarsest
  form (SQLite FTS5 trigram, tables `page_search` and `page_search_fts`) narrows pages; it is kept up
  to date after index runs and before searches, and rebuilt when the installed normalizers change.
  `settings.search` (engine, snippet context, a level per normalizer), `SearchSortBy`, and the errors
  `SearchError`, `SearchUnavailableError`, `SearchOptionError` and `SearchQueryError` (90 to 93).
- **Hybrid tier** (`index.run(tier="hybrid")`): local first; pages at or above
  `settings.tiers.min_size_factor` (and pages in the chosen OCR phases) go to the `github` tier; each
  page is paid from the wallet of the tier that reads it, and a page GitHub can't pay for is read
  locally. Pages away are collected like a plain `github` run.
- **GitHub runner** — now the free, optional `vethuq-addon-github` add-on (`pip install
  "VethuQ[github]"`; premium repository), which provides the `github` processing tier. `GitHub(client)`
  (`from vethuq.addons.github import GitHub`) has `setup`, `status`, `update`, `remove`, `runner` and
  `versions`; index runs send pages to the runner through the job protocol (see `github/`), collect
  the encrypted results and delete everything the job left in the repository. Core no longer has
  `client.github`, `vethuq.github`, the `GitHub*` errors or the `pynacl` dependency. The reusable
  workflow `.github/workflows/github-ocr.yml` and the layout are in `github/`; this replaces the
  separate `VethuQ-github-tier` repository.
- Internal tables `credit_grants`, `credit_ledger`, `usage_daily` and `usage_failures`.
- Internal tables `pdf_pages`, `pdf_pages_quick`, `document_languages` and `index_runs`.
- **Logs** (`client.logs`, types in `vethuq.logs`): one class per log (`DatabaseLog`, `IndexLog`,
  `UiLog`, `CliLog`, `PolicyLog`) with `file`, `tail`, `read` (filter by level, day and text; sort by
  time), `follow`, `export` and `logger`. Daily files with retention and safe rotation;
  `LogEntry`, `LogFile`, `LogComponent` and `LogLevel`.
- **Version** (`client.version`): `VersionDetails` with the VethuQ, Python, platform and database
  schema versions. The lists of installed file types, search engines, OCR engines, OCR languages,
  add-ons and bundles are placeholders for now.
- **Database schema version**: a `schema_version` table. A database written by a newer VethuQ is
  refused with `SchemaVersionError`; an older one is migrated step by step.
- **Policy** (`client.policy`, types in `vethuq.policy`): fetches the signed `policy.json`, verifies
  its Ed25519 signature, protects against rollback, supports key revocation, caches it in
  `<data root>/policy/`, and falls back to a built-in baseline. It never raises and fetches nothing
  unless asked. `VETHUQ_POLICY_URLS` overrides the URLs.
- **Updates** (`client.updates`, types in `vethuq.updates`): `status`, `check` and `feature`, with
  `UpdateResult`, `FeatureAccess`, snooze, skip-version and the `VETHUQ_UPDATE_CHECK` override.
  The signed policy is the only source of update information.
- **Paths** (`vethuq.Paths`): read-only locations of the data folder, database, backups, run, logs
  and policy folders. The data root comes from `VETHUQ_HOME`, then the saved `db.json`, then the
  platform default.
- **Errors** (`vethuq.errors`): a `VethuQError` root with `message`, `hint` and `exit_code`.

  | Exit code | Errors |
  |---|---|
  | 1 | `VethuQError`, `StartupError` |
  | 10 to 16 | `InvalidConfigError`, `DataFolderNotWritableError`, `CorruptDatabaseError`, `OcrModelMissingError`, `SchemaVersionError`, `StaleLockError`, `LanguageUnavailableError` |
  | 20 to 24 | `SourceError`, `SourcePathError`, `SourceAlreadyExistsError`, `SourceNotFoundError`, `SourceNotRemovedError` |
  | 30, 31 | `SettingsError`, `InvalidSettingValueError` |
  | 40 to 42 | `LogError`, `LogNotFoundError`, `InvalidLogRequestError` |
  | 50 to 52 | `IndexingError`, `IndexAlreadyRunningError`, `IndexRunNotFoundError` |
  | 60 to 62 | `CreditsError`, `InvalidGrantError`, `CreditsExhaustedError` |
  | 80, 81 | `TierError`, `TierUnavailableError` |
  | 70 to 74 | `GitHubError`, `GitHubAuthError`, `GitHubSetupError`, `GitHubNotSetUpError`, `GitHubUnavailableError` |

- **Database integrity check** (`client.db`, types in `vethuq.db`): `integrity_check(quick=False)` and
  `integrity_status()`, with `IntegrityCheckResult` and `IntegrityCheckMode`. The check runs by itself
  when the database is opened (`AUTO` once per interval, `ENABLE`, or `DISABLE`) and its result is saved
  and logged. A failed check, or a file SQLite can't read, raises `CorruptDatabaseError`; the check
  itself works on a database VethuQ refuses to open. Settings in `client.settings.database`.
- Opening the database permanently deletes the sources removed longer ago than the retention.
- **Add-ons** (`client.addons`, types in `vethuq.addons`): finds installed add-ons by their
  `vethuq.addons` entry point, lists them as `AddonInfo` with an `AddonStatus`, and gives each
  namespaced settings (`client.addons.settings(id)`). `from vethuq.addons.<id> import ...` reaches an
  installed add-on's public classes. Two best-effort hooks: after the database opens and before a
  schema migration. VethuQ deploys no add-on and works unchanged without them.
- Policy: `Policy.addons` (`AddonPolicy`: `enabled`, `latest`, `minimum_supported`, `min_client`,
  `message`) and `Policy.revoked_licence_ids`.
- Dependencies: `platformdirs~=4.0`, `sqlalchemy~=2.0`, `cryptography~=50.0`, `packaging~=26.0`,
  `vethuq-addon-api~=0.1`, `vethuq-addon-english~=0.1`.
- Job protocol v1 and the worker (package `vethuq-worker`, see `github/protocol/v1`): the format
  the GitHub processing tier will use to send pages to a runner and read the answer. No change to
  VethuQ's own API. Also the worker image's Dockerfile and build workflow
  (`github/image`, `.github/workflows/github-image.yml`).

### Notes
- The production policy signing keys are not built in yet, so `client.policy.refresh()` makes no
  request and reports `SKIPPED`.
- Only the `pip` distribution is supported by the update check. The desktop app's installer
  version is added when that app exists.
- Everything other than the names documented in the README is internal and may change without
  notice.
