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

`vethuq_core.ocr.run_ocr(conn, source)` walks a registered source
(recursively for folders), runs PaddleOCR (`lang="en"`) on every
supported file, and writes the extracted text to SQLite. Unsupported
extensions are skipped silently. PDFs are rasterized page-by-page via
PyMuPDF before OCR; PNG/JPEG files are OCR'd directly.

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
| `document_index` | One row per OCR'd file: `source_id`, `file_path` (unique), `file_type` (`pdf`\|`image`), `status` (`pending`\|`indexed`\|`error`\|`removed`), `error_message`, `indexed_at`, `file_size_bytes`, `mtime` (file's last-modified time, used to cheaply rule out unchanged files before re-hashing), `checksum` (SHA-256 of file contents), `duplicate_of_id` (self-FK; set when this file's checksum matches an already-indexed original, in which case OCR is skipped and this row has no rows of its own in the pages tables — it reuses the original's), `removed_at` (set when the file goes missing from its still-active source; mirrors `sources.removed_at`). Central table joining the type-specific pages tables. |
| `pdf_pages` | One row per PDF page: `document_id`, `page_number`, `ocr_text`, `confidence`. |
| `image_pages` | One row per PNG/JPEG file (no `page_number` — single image): `document_id`, `ocr_text`, `confidence`. |
| `processing_metrics` | One row per `file_type`, holding running averages (`document_count`, `avg_duration_seconds`, `avg_peak_memory_mb`, `avg_cpu_percent`) folded in after each successfully indexed document. Feeds future ETA estimates for `vethuq index run`. |
| `confidence_metrics` | One row per (`file_type`, `process_type`) pair (`process_type` is `native`\|`ocr`\|`mixed`), holding `page_count` and a running `avg_confidence` folded in per page after each successfully indexed document. Kept separate from `processing_metrics` so native pages' near-100% confidence doesn't dilute the OCR/mixed signal. |

A PaddleOCR engine instance is lazily created and reused per *thread*
(`vethuq_core.ocr._get_engine`, backed by `threading.local`) since model
init is expensive — a background run with multiple worker threads gets one
engine per thread, so OCR inference itself parallelizes, at the cost of
one engine's memory footprint per worker. A failure on one file is
recorded on that file's `document_index` row (`status='error'`,
`error_message`) without aborting the rest of the source; `sources.status`
reflects the overall outcome (`indexed` if all files succeeded, `error` if
any failed).

### Background indexing: worker threads

`vethuq_core.index_runner._run_worker` (the detached process `vethuq
index run`/`restart` launches) no longer processes one source at a time:
`vethuq_core.ocr.run_ocr_batch` flattens every targeted source's pending
files into a single list ordered by filename (`Path.name`, not the full
path or source grouping) before processing, so a run over multiple
sources reads as them indexing in parallel rather than strictly one
source at a time.

How many files are actually OCR'd concurrently is controlled by the
`thread_workers` setting (`vethuq_core.settings`; CLI: `vethuq settings
index thread-workers set/show`) — `0` (default) processes the list
sequentially in the calling thread with no pool at all; `1`-`8` uses a
fixed-size `ThreadPoolExecutor`; `auto` uses an elastic pool
(`vethuq_core.ocr._run_auto_elastic`) that re-resolves the active worker
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

Duplicate detection (`vethuq_core.ocr._upsert_document`) hashes every file
(SHA-256) as it's processed and, if another *indexed*, non-duplicate
document already has that checksum, links the new one to it via
`duplicate_of_id` instead of running OCR — duplicates are detected
globally across all sources, not just within one. Search and `index
status` still show a duplicate as its own result/row (reusing the
original's OCR text), just flagged as a duplicate. If the original is
later purged (see the removed-source retention window below), the
earliest-indexed surviving duplicate is promoted in its place: it
inherits the original's `pdf_pages`/`image_pages` rows and any other
duplicates are repointed to it (`vethuq_core.sources._promote_surviving_duplicate`).

Modified-file detection (`vethuq_core.ocr._has_content_changed`) lets
`vethuq index run` (`only_new_files=True`) also pick up files whose
content changed since they were last indexed, not just newly-added ones.
For each already-`indexed` file, its current mtime/size are compared
against the values stored on its `document_index` row; only if either
differs is the file's checksum recomputed and compared against the
stored one, to confirm an actual content change before re-running OCR on
it. This avoids re-hashing every file's full contents on every run for
large, mostly-unchanged sources.

If a modified file was itself an original that other documents were
deduped against, `_upsert_document` promotes the earliest of those
duplicates (via the same `_promote_surviving_duplicate` used for purging,
above) before applying the new checksum — otherwise those still-unchanged
duplicates would silently keep reusing what's about to become this
document's new, unrelated OCR text.

Rename/move and removal detection
(`vethuq_core.ocr._reconcile_renamed_and_removed_files`) runs before the
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
row "wins" because a removed original's pages are handed off to a
surviving duplicate via `_promote_surviving_duplicate` when it's actually
purged, so no OCR text is ever lost or shown against the wrong content.
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
