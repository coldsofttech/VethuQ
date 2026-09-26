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
| `document_index` | One row per OCR'd file: `source_id`, `file_path` (unique), `file_type` (`pdf`\|`image`), `status` (`pending`\|`indexed`\|`error`), `error_message`, `indexed_at`. Central table joining the type-specific pages tables. |
| `pdf_pages` | One row per PDF page: `document_id`, `page_number`, `ocr_text`, `confidence`. |
| `image_pages` | One row per PNG/JPEG file (no `page_number` — single image): `document_id`, `ocr_text`, `confidence`. |

A single PaddleOCR engine instance is lazily created and reused per
process (`vethuq_core.ocr._get_engine`) since model init is expensive.
A failure on one file is recorded on that file's `document_index` row
(`status='error'`, `error_message`) without aborting the rest of the
source; `sources.status` reflects the overall outcome (`indexed` if all
files succeeded, `error` if any failed).

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
