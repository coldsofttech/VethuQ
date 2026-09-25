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
| `vethuq-core` | Document model, ingest, OCR (Tesseract), SQLite/FTS5 indexing, embeddings, search, source registration | Free |
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
