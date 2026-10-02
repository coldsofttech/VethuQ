# Repository structure and package plan

VethuQ is built as a **uv workspace monorepo**: one repository, multiple
installable Python packages under `packages/`, rather than a single
monolithic package or separate repos per product tier. This lets each
commercial tier (Free → Basic → Lite → Pro → Premium → V5 AI add-ons)
install only the dependencies it needs, while the whole platform evolves
as one codebase.

See `.temp/requirements/*.md` for the full product/technical requirements
this plan is derived from.

## Current state

Built so far: `packages/vethuq-core`, `packages/vethuq-cli`, and
`packages/vethuq-ui`. Everything else below is the **planned** package
map — build them incrementally as tiers require them, not up front.

`packages/vethuq` is a fourth, different kind of package: the only one
published to PyPI (`pip install vethuq`). `packages/vethuq/scripts/merge_sources.py`
vendors `vethuq-core` + `vethuq-cli`'s source into it at build time (as
`vethuq._core` / `vethuq._cli`, generated and gitignored, not committed)
so tech users get `import vethuq` and the `vethuq` CLI from one
distribution, without `vethuq-core`/`vethuq-cli` ever being independently
installable from PyPI. See `scripts/dev/release.py` to build/verify it
locally, and `.github/workflows/release.yml` for the publish workflow.

## Planned package map

| Package | Purpose | Introduced by tier |
| --- | --- | --- |
| `vethuq-core` | Document model, ingest, OCR (PaddleOCR), SQLite/FTS5 indexing, embeddings, search, source registration | Free |
| `vethuq-cli` | CLI (Typer) | Free |
| `vethuq-ui` | Desktop UI (Tkinter) | Free |
| `vethuq-entitlements` | Tier/capability flags, license enforcement — cross-cutting, depended on by everything | Free (built early, per requirements §13) |
| `vethuq-intelligence` | Classification, entities, relationships, similarity, tables, timelines | Basic/Lite/Pro |
| `vethuq-security` | Auth, authz, tenant isolation, audit logging | Premium |
| `vethuq-sdk` | Python SDK client | Pro |
| `vethuq-api` | REST API (framework TBD — deferred) | Pro |
| `vethuq-mcp` | MCP server, generic + domain SKILLS | Premium / V4 |
| `vethuq-ai` | AI abstraction layer: provider-independent (Bedrock/local/hybrid), AI application services | V5 |

Expected intra-workspace dependency direction (later packages depend on
earlier ones, never the reverse):

```
vethuq-entitlements
        ▲
        │
   vethuq-core ──► vethuq-intelligence
        ▲   ▲             ▲
        │   │             │
   vethuq-cli │      vethuq-sdk ──► vethuq-api
        │   │             ▲
   vethuq-ui │             │
        │  vethuq-security │
        │             │
        └──────── vethuq-mcp ◄──── vethuq-ai
```

## Sources (files/folders as OCR/indexing input)

`vethuq_core.sources` is the single source of truth for registering files
and folders as VethuQ sources; both `vethuq-cli` (`vethuq source ...`) and
`vethuq-ui` (toolbar "Add Folder"/"Add File" buttons) call it directly
rather than duplicating logic. Folders are always indexed recursively —
there is no non-recursive mode.

Storage: a per-user SQLite database at
`platformdirs.user_data_dir("VethuQ")/vethuq.db` (e.g.
`%APPDATA%\VethuQ\vethuq.db` on Windows), with a `sources` table:

| Column | Notes |
| --- | --- |
| `id` | autoincrement primary key |
| `path` | resolved absolute path, unique (dedupes relative vs. absolute) |
| `source_type` | `file` \| `folder` |
| `status` | `pending` \| `indexed` \| `error` \| `removed` — updated later by the indexing pipeline |
| `added_at` | ISO-8601 UTC timestamp |
| `last_scanned_at` | nullable, set by the indexing pipeline |
| `is_active` | soft-delete flag; `remove_source` sets this to 0 rather than deleting the row |

A one-row `schema_version` table exists as a hook for future migrations,
without a full migration framework yet.

## OCR indexing pipeline

`vethuq_core.ocr.Quick.run(conn, source)` walks a registered source
(recursively for folders), runs PaddleOCR (`lang="en"`) on every
supported file, and writes the extracted text to SQLite. Unsupported
extensions are skipped silently. PDFs are rasterized page-by-page via
PyMuPDF before OCR; PNG/JPEG files are OCR'd directly; `.html`/`.htm`/`.xhtml` and `.xml` files are parsed as markup (encoding auto-detected) with no OCR.

Trigger model:
- CLI: `add_source` only registers a source (`status='pending'`); a
  separate `vethuq index run` command processes all pending sources.
- Desktop UI: a background daemon thread polls for pending sources every
  `_INDEX_POLL_INTERVAL_MS` (5s) and runs them automatically, using its
  own SQLite connection (connections aren't thread-safe) and marshalling
  UI refreshes back via `Tk.after`.

Storage, alongside `sources`:

| Table | Purpose |
| --- | --- |
| `documents` | One row per logical document, independent of any physical file path: just `id` and `created_at`. Exists so a document's identity survives renames, moves, and having more than one physical copy — see "Logical documents" below. |
| `document_index` | One row per OCR'd physical file: `source_id`, `document_id` (FK to `documents`; every row has one), `file_path` (unique), `file_type` (`pdf`\|`image`\|`html`\|`xml`), `status` (`pending`\|`processing`\|`indexed`\|`error`\|`removed` — set to `processing` once `started_at` is recorded, for a file actively being worked on), `error_message`, `indexed_at`, `file_size_bytes`, `mtime` (file's last-modified time as a float epoch, used to cheaply rule out unchanged files before re-hashing), `sha256` (SHA-256 of file contents), `created_at`/`modified_at` (OS-level file creation/modification timestamps captured at scan time - `created_at` uses the platform's actual file-birth time where the OS exposes one, falling back to the modification time on platforms that don't, e.g. Linux), `removed_at` (set when the file goes missing from its still-active source; mirrors `sources.removed_at`). Central table joining the type-specific pages tables. |
| `pdf_pages` | One row per PDF page: `document_id` (this one's a `document_index.id`, not `documents.id` — see "Logical documents"), `page_number`, `ocr_text`, `confidence`. |
| `markup_pages` | One row per HTML or XML file: `document_id` (a `document_index.id`), `ocr_text` (text extracted from the markup; XML values are prefixed with their element path), `confidence` (1.0 for a declared/UTF-8 encoding, lower when guessed or when malformed XML was read as loose text), `source` (always `native`), `encoding`. |
| `image_pages` | One row per PNG/JPEG file (no `page_number` — single image): `document_id` (a `document_index.id`), `ocr_text`, `confidence`. |
| `processing_metrics` | One row per `file_type`, holding running averages (`document_count`, `avg_duration_seconds`, `avg_peak_memory_mb`, `avg_cpu_percent`) folded in after each successfully indexed document. Feeds future ETA estimates for `vethuq index run`. |
| `confidence_metrics` | One row per (`file_type`, `process_type`) pair (`process_type` is `native`\|`ocr`\|`mixed`), holding `page_count` and a running `avg_confidence` folded in per page after each successfully indexed document. Kept separate from `processing_metrics` so native pages' near-100% confidence doesn't dilute the OCR/mixed signal. |

A PaddleOCR engine instance is lazily created and reused per *thread*
(`vethuq_core.ocr.Engine.get`, backed by `threading.local`) since model
init is expensive — a background run with multiple worker threads gets one
engine per thread, so OCR inference itself parallelizes, at the cost of
one engine's memory footprint per worker. A failure on one file is
recorded on that file's `document_index` row (`status='error'`,
`error_message`) without aborting the rest of the source; `sources.status`
reflects the overall outcome (`indexed` if all files succeeded, `error` if
any failed).

### Background indexing: worker threads

`vethuq_core.index.runner.IndexRunner._run_worker` (the detached process `vethuq
index run`/`restart` launches) no longer processes one source at a time:
`vethuq_core.ocr.Quick.run_batch` flattens every targeted source's pending
files into a single list ordered by filename (`Path.name`, not the full
path or source grouping) before processing, so a run over multiple
sources reads as them indexing in parallel rather than strictly one
source at a time.

How many files are actually OCR'd concurrently is controlled by the
`thread_workers` setting (`vethuq_core.settings`; CLI: `vethuq settings
index thread-workers set/show`) — `0` (default) processes the list
sequentially in the calling thread with no pool at all; `1`-`8` uses a
fixed-size `ThreadPoolExecutor`; `auto` uses an elastic pool
(`vethuq_core.ocr.Quick.run_auto_elastic`) that re-resolves the active worker
count after every file via `resolve_thread_workers`, from current
CPU/memory headroom (`psutil`) and the file-type mix (PDFs weighted
heavier than images) still remaining — up to `min(THREAD_WORKERS_MAX,
len(pending))` worker threads are spawned up front, but only the current
active count of them (by slot index) actually pull work at a time; the
rest just idle-poll, so the pool grows or shrinks without spinning up or
tearing down OS threads mid-run.

Since worker threads share one sqlite connection (opened with
`check_same_thread=False`), every read/write against it — including the
`thread_workers` setting lookup on each re-resolution — is serialized
through a single `threading.Lock` (`db_lock`); only the OCR inference
itself runs unlocked, which is the actual point of the parallelism.

### Claiming a file for processing

The PID lock file (`index.lock`) that `IndexRunner.start_run` uses to stop
a second `vethuq index run`/the desktop app's background poll from starting
concurrently has a check-then-write race of its own (checking the lock is
free and creating it aren't atomic), so two index runs *can* end up live at
once and pick the same file. `Document.upsert_index` (in
`db/queries/documents.py`) guards against that at the row level instead:
claiming a file is a single atomic
`INSERT ... ON CONFLICT DO UPDATE ... WHERE status != 'processing'`, so a
run only wins the claim (and gets to OCR the file) if no other run already
has it `processing`; a losing run's `Document.upsert` (in
`ocr/document.py`) returns `None` and leaves the file alone entirely, on
the assumption whichever run holds the claim will finish it. The same claim
also protects a single run's own worker threads from ever double-processing
one `document_index` row.

A row can be left claimed forever by a run that never got to mark it
`indexed`/`error` - a hard crash (killed before its `except`/`finally` can
run), or a `vethuq index stop` that had to force-kill a worker past its
timeout. `IndexRunner` resets any such row back to `error` (retryable by a
normal run or `vethuq index restart`) at each point it can tell for certain
nothing is still working on it: `_run_worker`'s own crash handler (the
common case - most unhandled exceptions still let Python's `except` run),
`_reconcile_orphaned_run` (a hard crash that skipped even that, detected via
the stale lock left behind, next time a run starts), and `request_stop`
right after a force-kill. A run that stops cooperatively never needs this:
it only checks the stop signal between files, so nothing is left mid-claim
when it exits on its own.

### Logical documents

`documents` represents a document's identity independent of any one
physical file: `document_index.document_id` is a required FK to it, so
every physical file belongs to exactly one logical document. This is what
duplicate content shares — two `document_index` rows with identical bytes
point at the *same* `documents.id`, rather than one physically chaining to
the other. Only one physical row per logical document actually carries OCR
pages (in `pdf_pages`/`image_pages`, keyed by `document_index.id` — not
`documents.id`); the rest are checksum links with no page rows of their
own, and readers resolve which row is the carrier by checking which one
actually has page rows for that `document_id` group.

Duplicate detection (`vethuq_core.ocr.Document.upsert`) hashes every file
(SHA-256) as it's processed and, if another *indexed* document already has
that checksum, links the new one to that document's `document_id` instead
of running OCR — duplicates are detected globally across all sources, not
just within one. Search and `index status` still show a duplicate as its
own result/row (reusing the carrier's OCR text), just flagged as a
duplicate. If the row carrying the pages is later deleted (purged, or its
content changes to something else — see below), the earliest surviving row
still sharing its `document_id` is promoted to carry those pages instead
(`vethuq_core.sources._promote_surviving_duplicate`); nothing needs
repointing on the other rows, since the shared `document_id` never moved.
If no row is left referencing a `documents` row afterward, it's deleted too
(`vethuq_core.sources._prune_orphaned_documents`) rather than lingering as
dead weight.

Modified-file detection (`vethuq_core.ocr.Document.has_content_changed`) lets
`vethuq index run` (`only_new_files=True`) also pick up files whose
content changed since they were last indexed, not just newly-added ones.
For each already-`indexed` file, its current mtime/size are compared
against the values stored on its `document_index` row; only if either
differs is the file's checksum recomputed and compared against the
stored one, to confirm an actual content change before re-running OCR on
it. This avoids re-hashing every file's full contents on every run for
large, mostly-unchanged sources.

If a modified file was itself carrying the OCR pages other documents shared
its `document_id` for, `_upsert_document` promotes the earliest of those
peers (via the same `_promote_surviving_duplicate` used for purging, above)
before applying the new checksum and moving this row on to its own new
(or separately matched) `document_id` — otherwise those still-unchanged
peers would silently keep reusing what's about to become this document's
new, unrelated OCR text. If that leaves the old `documents` row with no
other physical row referencing it, it's pruned.

Rename/move and removal detection
(`vethuq_core.ocr.Document.reconcile_renamed_and_removed`) runs before the
main indexing loop whenever `vethuq index run` scans an already-indexed
source. It compares the source's tracked file paths against what's
actually on disk: a brand-new path whose checksum exactly matches a
tracked path that's no longer there is treated as that file renamed or
moved — the existing row's `file_path` is updated in place and OCR isn't
re-run — while a tracked path that's gone missing and wasn't claimed by a
rename is marked `status='removed'` (`removed_at` set) rather than
deleted outright, in case the file reappears. When several files share a
checksum (e.g. two identical files, one deleted and one renamed), pairing
is deterministic but otherwise arbitrary; this is safe regardless of which
row "wins" because a removed carrier's pages are handed off to a
surviving peer sharing its `document_id` via `_promote_surviving_duplicate`
when it's actually purged, so no OCR text is ever lost or shown against the
wrong content.
`purge_expired_removed_documents` (mirroring
`purge_expired_removed_sources`, and sharing its retention setting)
permanently deletes documents that have stayed `removed` past the
retention window. A `removed` document is excluded from search (which
only matches `status='indexed'` rows) but still shows up in `index
status`, flagged with that status, until it's purged.

## Conventions per package

- `src/<pkg_name>/` layout (import name uses underscores, distribution
  name uses hyphens, e.g. `vethuq-core` → `vethuq_core`).
- `tests/` mirrors the package's own `src/` layout.
- Each package has its own `pyproject.toml` (hatchling build backend) and
  is registered in the root `pyproject.toml` under
  `[tool.uv.workspace] members` (via the `packages/*` glob) and
  `[tool.uv.sources]`.
- Root `pyproject.toml` holds shared dev tooling config (`ruff`, `mypy`,
  `pytest`) and the `dev` dependency group; it is not itself published.

## Open decisions (deferred, not yet made)

- REST API framework for `vethuq-api` (FastAPI vs. Flask) — deferred
  until that package is actually built.
- Whether `vethuq-mcp` and `vethuq-sdk` end up as separate distributions
  long-term or get merged — revisit once V4 work starts.
