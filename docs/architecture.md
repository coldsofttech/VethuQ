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

| Package               | Purpose                                                                                                | Introduced by tier |
| --------------------- | ------------------------------------------------------------------------------------------------------ | ------------------ |
| `vethuq-core`         | Document model, ingest, OCR (PaddleOCR), SQLite/FTS5 indexing, embeddings, search, source registration | Free               |
| `vethuq-cli`          | CLI (Typer)                                                                                            | Free               |
| `vethuq-ui`           | Desktop UI (Tkinter)                                                                                   | Free               |
| `vethuq-entitlements` | Tier/capability flags, license enforcement — cross-cutting, depended on by everything                  | Free               |
| `vethuq-intelligence` | Classification, entities, relationships, similarity, tables, timelines                                 | Basic/Lite/Pro     |
| `vethuq-security`     | Auth, authz, tenant isolation, audit logging                                                           | Premium            |
| `vethuq-sdk`          | Python SDK client                                                                                      | Pro                |
| `vethuq-api`          | REST API (framework TBD — deferred)                                                                    | Pro                |
| `vethuq-mcp`          | MCP server, generic + domain SKILLS                                                                    | Premium / V4       |
| `vethuq-ai`           | AI abstraction layer: provider-independent (Bedrock/local/hybrid), AI application services             | V5                 |

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
`platformdirs.user_data_dir("VethuQ")/db/vethuq.db` (e.g.
`%APPDATA%\VethuQ\db\vethuq.db` on Windows), with a `sources` table:

| Column            | Notes                                                                                   |
| ----------------- | --------------------------------------------------------------------------------------- |
| `id`              | autoincrement primary key                                                               |
| `path`            | resolved absolute path, unique (dedupes relative vs. absolute)                          |
| `source_type`     | `file` \| `folder`                                                                      |
| `status`          | `pending` \| `indexed` \| `error` \| `removed` — updated later by the indexing pipeline |
| `added_at`        | ISO-8601 UTC timestamp                                                                  |
| `last_scanned_at` | nullable, set by the indexing pipeline                                                  |
| `is_active`       | soft-delete flag; `remove_source` sets this to 0 rather than deleting the row           |

A one-row `schema_version` table exists as a hook for future migrations,
without a full migration framework yet.

## OCR indexing pipeline

`vethuq_core.ocr.Quick.run(storage, source)` walks a registered source
(recursively for folders), runs OCR on every supported file through the
engine-agnostic `vethuq_core.ocr.engines` interface (see "OCR engines"
below; PaddleOCR with `lang="en"` today), and writes the extracted text to
SQLite. Unsupported
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

| Table                | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `documents`          | One row per logical document, independent of any physical file path: just `id` and `created_at`. Exists so a document's identity survives renames, moves, and having more than one physical copy — see "Logical documents" below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `document_index`     | One row per OCR'd physical file: `source_id`, `document_id` (FK to `documents`; every row has one), `file_path` (unique), `file_type` (`pdf`\|`image`), `status` (`pending`\|`processing`\|`indexed`\|`error`\|`removed` — set to `processing` once `started_at` is recorded, for a file actively being worked on), `error_message`, `indexed_at`, `file_size_bytes`, `mtime` (file's last-modified time as a float epoch, used to cheaply rule out unchanged files before re-hashing), `sha256` (SHA-256 of file contents), `created_at`/`modified_at` (OS-level file creation/modification timestamps captured at scan time - `created_at` uses the platform's actual file-birth time where the OS exposes one, falling back to the modification time on platforms that don't, e.g. Linux), `removed_at` (set when the file goes missing from its still-active source; mirrors `sources.removed_at`). Central table joining the type-specific pages tables. |
| `pdf_pages`          | One row per PDF page: `document_id` (this one's a `document_index.id`, not `documents.id` — see "Logical documents"), `page_number`, `ocr_text`, `confidence`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `image_pages`        | One row per PNG/JPEG file (no `page_number` — single image): `document_id` (a `document_index.id`), `ocr_text`, `confidence`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `processing_metrics` | One row per (`phase`, `extension`, `size_bucket`) (`extension` is the file's lowercase extension without the dot, `jpeg` folded into `jpg`; `file_type` is kept for grouping), holding running averages (`document_count`, `avg_duration_seconds`, `avg_peak_memory_mb`, `avg_cpu_percent`) folded in after each successfully indexed document. Feeds future ETA estimates for `vethuq index run`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `confidence_metrics` | One row per (`extension`, `process_type`) pair (`process_type` is `native`\|`ocr`\|`mixed`), holding `page_count` and a running `avg_confidence` folded in per page after each successfully indexed document. Kept separate from `processing_metrics` so native pages' near-100% confidence doesn't dilute the OCR/mixed signal.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

An OCR engine instance is lazily created and reused per *thread*
(`vethuq_core.ocr.engines.Engines.get`, backed by `threading.local`) since
model init is expensive — a background run with multiple worker threads gets one
engine per thread, so OCR inference itself parallelizes, at the cost of
one engine's memory footprint per worker. A failure on one file is
recorded on that file's `document_index` row (`status='error'`,
`error_message`) without aborting the rest of the source; `sources.status`
reflects the overall outcome (`indexed` if all files succeeded, `error` if
any failed).

### OCR engines

`vethuq_core.ocr` never talks to a concrete OCR library. It depends on
`vethuq_core.ocr.engines`:

- `OcrEngine` (a `Protocol`, in `ocr/engines/base.py`) — `name` (engine
  label with version, stored as `ocr_engine`), `language` (stored as
  `language`) and `recognize(image) -> OcrResult`, where `image` is a file
  path or a BGR pixel array and `OcrResult` carries `text`, `confidence`, per-line `lines`,
  the engine's `engine`/`language` labels and the image's pixel size.
- `Engines.get(storage)` (`ocr/engines/registry.py`) — returns the calling
  thread's engine, constructing it on first use through the factory
  registered for `Engines.DEFAULT`.
- `PaddleOcrEngine` (`ocr/engines/paddle.py`) — the only implementation
  today. Only the registry imports it (lazily), so PaddleOCR/Paddle stay
  entirely behind the interface.

`OcrResult` holds plain values only, and `document_index`/`pdf_pages`/
`image_pages` store those values, so storage is engine-agnostic. Adding an
engine means writing an `OcrEngine` implementation and calling
`Engines.register(name, factory)`; nothing in `ocr/` or the schema changes.
Choosing between engines (and languages) isn't wired up yet — one engine and
language are supported for now.

### Storage access

Application code never touches `sqlite3` or `vethuq_core.db` directly; it
depends on the `Storage` interface in `vethuq_core.storage`:

- `Storage` (a `Protocol`, in `storage/base.py`) — the union of small
  per-table repositories (`SourceStore`, `DocumentStore`, `SettingsStore`,
  `StatsStore`, `IndexRunStore`, `OcrStore`, `IntegrityStore`) plus `transaction()`,
  `commit()` and `close()`. A collaborator can depend on just the slice it needs.
- `SqliteStorage` (`storage/sqlite.py`) — the SQLite implementation; each method
  delegates to the matching query method in `vethuq_core.db.queries`, which stays
  the only place SQL is written.
- `open_storage(db_path=None)` — connects (creating/migrating the schema) and
  returns a `Storage`. The CLI, desktop UI, Python library and core modules
  (`source`, `settings`, `stats`, `db.integrity`, `search`, `ocr`, `index`,
  readers' page storage, search engines) all take a `Storage`.

A test enforces that no core module outside `db/` and `storage/` imports
`sqlite3` or `vethuq_core.db`. Swapping the backing store means writing another
`Storage` implementation.

### Search engines

`vethuq_core.search.Search.indexed_content` is a facade over
`vethuq_core.search.engines`:

- `SearchEngine` (a `Protocol`, in `search/engines/base.py`) — `name` and
  `search(query, *, context_chars=None, case_sensitive=False, threshold=None, distance=None) -> list[SearchMatch]`.
  An engine may raise `SearchEngineUnavailable` when it can't serve queries.
- `SearchEngines.get(storage, name=None)` (`search/engines/registry.py`) — builds
  the engine registered under `name` (default `like`) on a `Storage`.
- Eight engines are registered (`SearchSettings.ENGINES` lists their names;
  shared helpers live in `SearchEngineHelpers`, `search/engines/common.py`):
  - `like` (`search/engines/like.py`) — substring match anywhere, even inside a
    word; case-insensitive unless `case_sensitive`. Narrows candidate pages via
    the trigram indexes (`pdf_pages_trigram`/`image_pages_trigram`) queried with `LIKE`.
  - `exact` (`search/engines/exact.py`) — the query as typed: case-sensitive and
    as a whole word (`Museum` doesn't match `museum` or `Museums`). Shares the
    trigram narrowing with `like`.
  - `full-text` (`search/engines/fulltext.py`) — whole-word, stemmed, ranked by
    BM25 (`SearchMatch.score`). Queries the word indexes
    (`pdf_pages_words`/`image_pages_words`, `unicode61` + `porter`, added in schema
    v28 and kept in sync by triggers) with `MATCH`; the query becomes a safe
    expression via `FullTextSearchEngine.build_match_expression` (`"phrase"`,
    `prefix*`, all terms required), and matches are located with FTS5's
    `highlight()`. Always case-insensitive.
  - `fuzzy` (`search/engines/fuzzy.py`) — whole words within a similarity
    threshold of the query's words, every word required, closest page first.
    Similarity is `1 − edits ÷ longer word` with optimal-string-alignment edits
    (a swap counts once), at most `MAX_EDITS` (2); words under
    `MIN_FUZZY_LENGTH` (4) and words with a digit must match exactly.
    Candidate pages come from the trigram index via `narrowing_expression`,
    which only narrows where it is provably lossless (an edit spoils at most 3
    trigrams) and otherwise examines every indexed page; each candidate's words
    are then scored in Python (`similarity`), so hits keep their exact spans and
    `SearchMatch.score` is the word's similarity. `SearchSettings.FUZZY_PRESETS`
    names the thresholds (`strict`, `balanced`, `loose`); a threshold may also be
    given as a percentage or a similarity (`SearchSettings.parse_fuzzy_threshold`).
  - `proximity` (`search/engines/proximity.py`) — passages where all of the
    query's terms (two or more words or `"phrases"`, parsed by
    `FullTextSearchEngine.parse_terms`) sit within N words of each other, in any
    order. FTS5's `NEAR(t1 t2 ..., N)` over the word index selects and ranks pages
    (N counts the words between the first and last term, other terms included);
    each term is then located again with `highlight()`
    (`Storage.get_pdf_term_highlights` / `get_image_term_highlights`) and
    `ProximitySearchEngine.find_clusters` turns the spans into passages, applying
    the same rule and merging overlaps, so each `SearchMatch` is one passage from
    first term to last. `SearchSettings.PROXIMITY_PRESETS` names the distances
    (`tight` 3, `medium` 10, `loose` 30); `parse_proximity_distance` also takes
    1-100. Always case-insensitive; fewer than two terms is a `SearchQueryError`.
  - Look-alike characters are not an engine but a *normalizer* (below): `like` reads them
    as the letters they stand for when its leetspeak level is on, using the trigram index over
    the recorded skeleton to find candidate pages and the folded text to find the match
    (`LikeSearchEngine._search_lookalikes`). The combined search runs `like` once with look-alikes on
    and records which normalizations each hit needed (`Normalizers.applied`, `SearchMatch.modifiers`).
  - `noise-fuzzy` (`search/engines/noise_fuzzy.py`) — the query's characters hidden by
    noise, look-alikes and typos at once, in the order the text is cleaned up: noise
    (whitespace and punctuation that can't be a look-alike; `Leet.is_noise`) is skipped,
    look-alikes are folded to a class letter (`Leet.classes(level)`, single characters only), and
    the rest is matched within the fuzzy threshold by the same edit rules as `fuzzy`
    (`FuzzySearchEngine.edit_distance`). The query goes through the same steps. A match is
    widened to the word edges it touches, then checked against the noise setting
    (`SearchSettings.NOISE_LEVELS`: most noise characters in a row, and in all) and scored by
    its cleanliness (1.0 as typed, less for each edit, look-alike and noise character).
    **The recorded skeleton:** `search/normalizers/leetspeak.py` reduces text to a skeleton (noise dropped,
    look-alikes folded as coarsely as any level does, lower-cased; one character per kept
    character). Pages store it as `noise_text`, written with the page (`Document.insert_*`,
    `Ocr.Page.update_text`), with a trigram index `<pages>_noise` kept in sync by triggers
    (`Document.noise_schema`, schema v29, backfilled by the migration and rebuilt by
    `rebuild-search`). Because a level or noise setting only ever matches a subset of what the
    skeleton matches, it is a sound pre-filter: `narrowing_expression` takes pages through the
    trigram index when the query is long enough for that (as in `fuzzy`), and
    `candidate_stretches` then searches the stored skeleton — occurrences when no edits are
    allowed, otherwise the stretches where enough of the query's two-character pieces fall
    together (a q-gram lemma, `n - 1 - 3k`) — so only those stretches of a page are read and
    verified. Pages without a recorded skeleton are always included.
  - `semantic` (`search/engines/semantic.py`) — passages that mean what the query means.
    It is the only engine that needs a model: `intfloat/multilingual-e5-small`, run with
    ONNX Runtime (`vethuq_core.semantic.OnnxEmbedder`: tokenizer from `tokenizers`, mean
    pooling, unit vectors) and downloaded on first use by `SemanticModel.download`
    (`huggingface_hub`) into `<data root>/models/semantic/`. The dependencies are the
    `search-semantic` extra (`onnxruntime`, `tokenizers`, `huggingface-hub`); `numpy` is a base
    dependency. `Embedders.get()` is the one place an embedder is made (and what tests replace
    with `Embedders.use`). **The index:** `Chunker` cuts a page's text into passages of a few
    sentences (400 characters at most, a span of the text so a hit can point at it);
    `SemanticIndex.sync` embeds the pages that have none and stores each passage's span and
    normalized float32 vector as a BLOB, in batches that each commit. **A separate, versioned
    store** (`db/queries/semantic.py`): the vectors are derived data and large, so they live in
    their own SQLite file, `<database name>.semantic.db` beside the main database, attached to
    every connection as the schema `semantic` (`Semantic.attach`, called by `Db.connect`;
    tables `meta`, `pages`, `chunks`). The main database stays small, its backups carry no
    vectors, and the store can be thrown away without losing anything that can't be computed
    again - a damaged file is recreated, `vethuq semantic clear` empties it (and gives the space
    back) and `db reset` / `db restore` discard it. Nothing in it can describe the wrong text:
    each page records the `model` and the `version` it was embedded with
    (`SemanticIndex.version()`: `SemanticIndex.VERSION` - bumped when chunking, text
    preparation, pooling or prefixes change - and `Chunker.MAX_CHARS`), pages of another version
    are never searched and `sync` drops and re-embeds them; the file has its own layout version
    (`Semantic.STORE_VERSION`) and a file of another layout is emptied; and it records the
    `database_id` (in the main `database_identity` table) it was built for, because page ids only mean something
    inside one database, so a store built for another one is emptied. Triggers on `pdf_pages` and
    `image_pages` can't write to an attached file, so a deleted page or one whose text changes is
    queued in `semantic_dirty` (main database) and the queue is applied to the store before it
    is next read; the queue is dropped when the store is empty. The next sync embeds those pages
    again.     rows are keyed by the model's name, so another model's vectors are separate. **Search:**
    the query is embedded (with E5's `query: ` prefix; passages get `passage: `), every chunk's
    vector of searchable pages is loaded into one numpy matrix and `matrix @ query` is the cosine
    similarity - brute force, which is milliseconds at 100k passages, so no vector database or
    SQLite extension is needed. Passages at or above the threshold
    (`SearchSettings.SEMANTIC_PRESETS`, `parse_semantic_threshold`) are grouped by page, the best
    `search_semantic_limit` pages kept, each with its best `MAX_HITS_PER_PAGE` passages, and the
    carriers' files (duplicates included) are fetched for them
    (`Semantic.list_page_rows`). It is not a tier of `Ranking`, so `all` never loads the model;
    `Ranking.BADGES` still labels its hits `Related`. A model that can't be downloaded or
    loaded raises `SearchEngineUnavailable`.
  - `HybridSearchEngine` (`search/engines/hybrid.py`) — what the registry returns for
    `semantic` when `search_semantic_combine` is `full-text` or `lexical`: both engines run and
    their pages are ranked together by reciprocal rank fusion (`1 / (60 + position)`, summed
    over the engines that found a page) because a cosine and a BM25 score can't be compared.
    Each hit keeps its own engine and `matched_by` lists the engines that found its page.
- `FallbackSearchEngine(primary, fallback)` — answers from `fallback` when
  `primary` raises `SearchEngineUnavailable`.

`Search.resolve_options` picks the engine, case sensitivity, (fuzzy only)
threshold, (proximity only) distance, (like and noise-fuzzy) leetspeak level and (noise-fuzzy only)
noise level from arguments and the `search_engine` /
`search_case_sensitive` / `search_fuzzy_threshold` / `search_proximity_distance`
/ `search_normalize_case` / `search_normalize_unicode` / `search_normalize_leetspeak` / `search_noise_level` / `search_semantic_threshold` (the threshold of `semantic`, which has its own presets) settings, rejecting (with `SearchOptionError`) combinations an engine can't honour.

### Normalizers

`vethuq_core.search.normalizers` mirrors `search.engines`: what an engine does is the *shape* of a
match (substring, whole word, ranked, edit distance, ...), what a normalizer does is decide what
counts as *the same character*, for the query and the page text alike.

- `base.py` — the `Normalizer` protocol (`name`, `levels`, `identity`, `fold(text, level)` returning
  a `Folded` - the text plus, when positions moved, where each character came from - and
  `char_table(level)`, a `str.translate` table when the fold is character for character) and
  `Folded.original(start, end)`, which maps a span of folded text back to the original.
- `common.py` — `Pipeline` (normalizers applied one after another, composing their position
  maps) and `NormalizerHelpers`.
- `registry.py` — `Normalizers.register / get / available / pipeline`; applied in `Normalizers.ORDER`:
  `unicode`, `case`, `leetspeak`.
- `case.py` (`match` | `ignore`), `unicode.py` (`off` | `basic` NFC | `full` NFKC and accents folded,
  traced back piece by piece) and `leetspeak.py` (`off` | `basic` | `standard` | `extended`: single
  characters folded into classes; also the skeleton and noise helpers the database and
  `noise-fuzzy` use).

The Unicode normalizer is applied by `like`, `exact`, `fuzzy` and `noise-fuzzy`: the query and the
page text are folded (`Pipeline.fold`), the engine matches on the folded text, and
`Folded.original` maps the spans back to the original so highlights and exports show what is on
the page. Each engine has its own default (`SearchSettings.UNICODE_DEFAULTS`): `exact` and `like`
`basic`, `fuzzy` and `noise-fuzzy` `full`; the stored setting (`auto` unless changed) or a
per-search flag overrides it, except for `exact`, which is strict and takes a level only from the
search itself.

**The normalized text:** pages also store `norm_text` — `Normalizers.index_form(text)`, the text
folded as coarsely as any normalization does (Unicode `full`, case ignored, look-alikes
`extended`) — with a trigram index over it (`pdf_pages_norm`, `image_pages_norm`), recorded at
write time and rebuilt by `rebuild-search`. Because the strictest level only ever matches a subset
of what the coarsest does, it is a sound pre-filter for every level: `like`, `exact` and `fuzzy`
narrow candidate pages through it (`SearchEngineHelpers.norm_match`, `narrowing_expression`),
`noise-fuzzy` through the skeleton index, and the folded text still has the final say, so a
setting never needs a reindex. Pages without recorded text are always candidates.

The settings are `search_normalize_case`, `search_normalize_unicode` and `search_normalize_leetspeak` (`auto` = each engine's
own default, or an explicit value for every engine that can honour it); the engine's own default
and what it supports is in the engine (`like`: look-alikes off; `noise-fuzzy`: `basic`).
`search/__init__.py` imports lazily so the database layer can import the normalizers (to record a
page's skeleton) without pulling in the engines, which import the database layer.

### Searching Telugu

What a *word* is lives in one place, `Scripts` (`vethuq_core.languages`): `Scripts.word_pattern()` is
`\w+` except that the whole Telugu block (letters, vowel signs, virama, digits) belongs to words, and a
zero-width joiner next to a Telugu character does too. `full-text`, `fuzzy`, `exact`'s boundaries and
`noise-fuzzy`'s word edges use it instead of `\w`/`isalnum`, which treat a Telugu vowel sign as
punctuation. For any other text it is `\w` exactly, so English tokenizes as it always did (pinned by
`tests/search/test_english_golden.py`).

- **Unicode normalizer.** `full` strips a combining mark (category Mn) only when the letter before
  it is in a script where marks are decoration (`Scripts.strips_marks`); Telugu vowel signs and the
  virama stay. In `full` a joiner after a Telugu character is dropped and Telugu digits become ASCII
  digits. `_units` keeps a Telugu sign with its letter, so a mark is never normalized without it and
  positions still trace back for highlighting.
- **Skeleton and noise.** `Leet.is_noise` and `Leet.kept()` no longer treat Telugu marks as noise, so a
  page's `noise_text` keeps them and `noise-fuzzy` compares real syllables rather than bare
  consonants. The look-alike classes are Latin only and are not touched.
- **Word index routing.** A query with a character of a mark-keeping script (`Scripts.has_mark_script`)
  is looked up in the `*_words_complex` indexes (schema v32) by `full-text` and `proximity`
  (`FullTextSearchEngine.needs_mark_aware_index`); everything else uses the plain indexes. The storage
  calls take `complex_index`, and `Document.words_index` names the table. `proximity` counts the words
  between terms with the tokenizer of the index it searched (`ProximitySearchEngine.token_starts`). If
  that index does not exist (an SQLite too old for the tokenizer) the engine raises
  `SearchEngineUnavailable`: searching the plain index would match consonant fragments, so it refuses;
  the combined search skips an engine that is unavailable, and the CLI reports it.
- **Snippets.** `SearchEngineHelpers.build_match` moves context boundaries off Telugu signs, so a
  snippet never starts on a sign without its letter or loses the sign of its last letter; other scripts'
  accents are cut exactly where they were.
- **What is deliberately not done.** No Telugu stemming (a rule-based stripper would be a later
  addition); `fuzzy` counts edits per code point, not per syllable; and `lexical` (a trigram-overlap
  engine) is unchanged.

### Combined search and ranking

`vethuq_core.ranking.search_all` (`search --engine all`, the default) runs every
engine, groups their hits by page and ranks the pages, returning `PageResult`s
(`search.search_indexed_pages`; `search_indexed_content(engine="all")` flattens them).
Engine scores aren't comparable, so ranking is by **match quality**, not by blending
numbers: `ENGINE_TIERS` orders `exact` > `like` > `lexical` > `proximity` > `full-text` > `fuzzy` > `noise-fuzzy`
(`proximity` above `full-text` because every page it finds `full-text` finds too;
`noise-fuzzy` last, as it is `fuzzy` with tolerance for noise). A normalization a hit needed
(`Normalizers.MODIFIERS`: `accents`, `look-alike`) is a modifier of its engine's badge, not a tier:
`Ranking.hit_rank` orders hits and pages by *matched as typed, then needing a modifier, then the
approximate engines (`fuzzy`, `noise-fuzzy`)*, each by engine, then by that engine's own signal
(hit count for `exact`/`like`, share matched as typed for modified hits, relevance for
`proximity`/`full-text`, best similarity for `fuzzy`), then by how many engines agreed, then by path
and page.
Since the engines' matches nest, a page is one result and overlapping hits are
merged (`_merge_overlapping`): the union span, labelled with the strictest engine,
listing every engine in `matched_by`; a `proximity` passage thereby absorbs the word
hits inside it. `ENGINE_BADGES` names the tiers for users (Exact, Contains, Near,
Word, Similar, Obscured, plus `ENGINE_MODIFIERS`, shown as `Contains · look-alike`) and is shared by the CLI and the UI. Each engine gets only the
options it accepts, and `proximity` is skipped for one-term queries.
`SearchMatch.start`/`end`/`engine`/`matched_by`/`modifiers` carry what the merge needs.

Adding an engine means writing a `SearchEngine` and calling
`SearchEngines.register(name, factory)`; engines coexist, so it can be selected
by name or chained in front of another as a fallback. Callers are unchanged.

### Languages and scripts

`vethuq_core.languages` says what a piece of text *is*, so OCR, normalizers and search never name a
language themselves:

- `Scripts` (no dependencies; the database layer imports it) lists the Unicode ranges of each
  writing system and whether Unicode `full` normalization may strip its combining marks
  (`Script.strips_marks`: Latin yes - an accent is not part of the letter; Telugu no - its vowel
  signs and virama are part of the syllable). `Scripts.contains/present/dominant` find the scripts
  in a text.
- `Languages` (loaded lazily, since it reads the OCR catalog) lists the enabled languages and which
  of them a text calls for.

Languages are manifests (`ocr/languages/manifests/<id>.json`: `script`, `paddle_lang`,
`native_label`, the `models` they need) like the OCR engines and search engines, and `sync_extras.py`
turns them into the `lang-<id>` extras and the installer's catalog. English is the default and always
enabled; any other language is a marker package (`vethuq-lang-te`) and counts as installed when its
module imports. It is *enabled* when it is also in the installer's selection (`languages.json`,
`{"enabled": [...]}`; no file means every installed language).

Schema v32 adds the language bookkeeping, none of which changes how existing (English) pages are
stored or searched:

| Column / table | Purpose |
| --- | --- |
| `sources.languages` | Comma-separated language ids a source is read in; `NULL` means use the setting. |
| `pdf_pages.ocr_langs`, `image_pages.ocr_langs` | Languages whose passes contributed to a page's text; empty (every page written before v32) means just the one in its `language` column. |
| `document_languages` | One row per (file, language) OCR pass, in the order they run: `position`, `status` (`pending`/`processing`/`done`/`error`/`skipped`), `source` (`default`/`auto`/`manual`), `confidence`, timestamps. Keyed by the `document_index` row that carries the pages; removed with it. |
| `pdf_pages_words_complex`, `image_pages_words_complex` | A second word index for scripts whose marks are part of the word. |

Schema v33 keys the two statistics tables by language too (`processing_metrics` and `confidence_metrics`
get a `language` column in their primary key; every earlier row becomes `en`). Confidence is
filed under the language each page was read in, a language pass folds its own confidence under its
language, deeper phases are filed under the language of the page, and a document's quick pass under
the language most of its pages were read in. Memory/CPU budgeting and the ETA average across
languages weighted by document count. Language passes' durations are not recorded yet.

**The mark-aware word index.** SQLite's `unicode61` tokenizer treats combining marks as separators, so
the plain word indexes split a Telugu word at every vowel sign (`అమ్మ` becomes `అమ` and `మ`). Rather
than change that tokenizer - which would change how every English page is indexed - the
`*_words_complex` indexes use `unicode61 ... categories 'L* N* Co Mn Mc'` (no stemming) and hold only
the pages that contain a character of such a script (`Scripts.keeps_marks_glob`, tested with `GLOB` in
the triggers). English pages never enter them and the plain indexes are untouched. They are
external-content tables like the others, kept in sync by triggers; the UPDATE trigger removes the old
entry and adds the new one in a single statement list so the order is fixed. FTS5's own `rebuild`
would index every page, so `Document.rebuild_search_index` empties them (`delete-all`) and refills them
from the matching pages. They need an SQLite new enough for the tokenizer's `categories` option
(probed once, `Document.complex_words_supported`); without it they are not created, a warning is
logged, and rebuilding them is a no-op.

### OCR languages: choosing, detecting, queueing

`vethuq_core.ocr.plan.LanguagePlan` resolves which languages a file may be read in, most
specific first: a per-run override (`--lang`, passed to the detached worker as its fourth
argument), the source's `languages`, then the `ocr_languages` setting (`auto` by default: every
enabled language, which is English alone on an install with no other). `LanguageSelection`
(`vethuq_core.languages.selection`) parses and validates the choice and returns `Candidates` -
the default language first, then the rest in catalog order. A language that is unknown, not
installed or not enabled fails with `LanguageUnavailableError` (and the index runner refuses the
run up front, `IndexRunner._check_languages`, so a detached worker never fails every file).

One candidate is read directly. With several, the first reads the file through the ordinary
quick pass (`Quick.process_file_once`; `Engines.get(storage, language)` builds an engine per
language and caches it per thread, and the default language is built and called exactly as
before), then `LanguagePlan.after_first_pass` decides what that read means using
`vethuq_core.ocr.detection.LanguageDetector`:

- a file with no scanned page (native text layer) shows its language by script - no OCR to queue;
- a read that is empty (too few characters to judge) or confident (recognizer confidence at
  least `MIN_CONFIDENCE`, and at least `MIN_SCRIPT_SHARE` of its characters in the language's
  script) settles the language and marks the other candidates `skipped`;
- otherwise the read is *unsure*: lines the language read below `MIN_LINE_CONFIDENCE` (or in
  another script) are dropped before the pages are stored, and the other candidates are queued
  as `pending` rows in `document_languages`, in order.

`PageResult` carries the engine's per-line scores in memory (`lines`, never stored) so the
dropping needs no extra storage. `vethuq_core.ocr.passes.LanguagePasses` then runs the queue
(see [ocr-phases.md](ocr-phases.md#languages)); the thresholds in `LanguageDetector` are
provisional and class constants so they can be tuned in one place.

English-only behaviour is guarded rather than assumed: every code path that names a language is
skipped when only the default language is involved, the default language's engine factory is
called with the arguments it always had, and the golden tests in
`tests/search/test_english_golden.py` pin the normalizers and tokenizer. With `lang-te` installed
the same files take one extra step (judging the English read) and nothing else unless English
doubts it.

### OCR models

`vethuq_core.ocr.models.OcrModels` finds, downloads and removes the OCR models without importing
PaddleX (the desktop UI and CLI do not ship it). Each model is a folder under
`<cache>/official_models/<name>` in PaddleX's own cache. Which models exist comes from the manifests:
the engine's (`ocr/engines/manifests/paddle.json`) lists the ones every language shares - detection
and page/line orientation - and each language's lists its recognizer. Downloading runs in a child
process (`ocr/models/fetch.py`; the worker executable in the desktop build, via its `--fetch-models`
flag) that is the only code importing PaddleX and prints one JSON status line per model. Clearing a
language keeps the shared models unless asked; `clean` removes only models VethuQ's manifests name,
never other folders in the shared cache. See `vethuq ocr models` in [CLI.md](CLI.md).

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

### Background service

`vethuq_core.background` lets indexing run through a long-lived service instead of a detached worker per command.

- **One entry point.** Every `index *` entry point (CLI, desktop app, `vethuq` package) calls `Dispatch.submit`, which is `IndexRunner.start_run` when the service is not installed (or `--one-off` was given) and otherwise validates the request the same way (`IndexRunner.validate_request`: source, languages) and inserts a row in the `index_jobs` table (schema v35). An identical job already waiting is reused, so periodic callers (the desktop rescan) cannot pile jobs up; finished jobs are pruned to the latest 100.
- **The service.** `vethuq-worker.exe --service` (Windows; `python -m vethuq_core.index.runner --service` under systemd) runs `ServiceHost`: claim the oldest queued job, start it with `IndexRunner.start_run` (the same call, so the run reads every setting from the database exactly as a one-off does and `index status|pause|resume|stop` keep working), wait for it, record the outcome, repeat. The run stays a separate worker process, so a native OCR crash does not take the service down. The worker executable is promoted, not duplicated: it is the service when started with `--service`, and the worker the service launches when started with the usual arguments.
- **Pause, stop, restart.** The service manager's pause pauses the active run and holds the queue (on Linux a `service.control` file in `run/` does the same); stop asks the run to stop between files and puts its job back in the queue, and a service that died mid-run re-queues the job it left `running`. A run stopped from outside (`index stop`) ends its job as `cancelled`.
- **Installing.** `BackgroundService` drives `sc.exe` (create/start/stop/pause/continue/delete) or `systemctl --user`. Creating a service needs administrator rights, so an unelevated Windows caller re-runs the action through `vethuq-worker.exe --service-control <action>` with a UAC prompt (`ShellExecuteEx` `runas`); the Inno Setup `backgroundservice` task runs the same command. The service is given `--home <data root>` so it uses the installing user's database whichever account it runs as. Reading the status needs no rights.
- **Not in the service.** `rebuild-search` is a foreground database operation, not an index run, and is unchanged.

### Data layout

All per-user data lives under `platformdirs.user_data_dir("VethuQ")`
(`%APPDATA%\VethuQ` on Windows), split by purpose (`vethuq_core.paths.Paths`):

| Folder  | Contents                                                                      |
| ------- | ----------------------------------------------------------------------------- |
| `db/`   | `vethuq.db` and SQLite's `-wal` / `-shm` files                                |
| `run/`  | runtime coordination files: `index.lock`, `index.control`, `index_state.json` |
| `logs/` | `database.log`, `index.log`, `ui.log`, `cli.log` (see below)                  |

`run/` and `logs/` sit next to the database's `db/` folder. A database left
directly in the data root by an older version is moved into `db/` the first
time the default path is resolved.

Each log file has one owner (`vethuq_core.logs.Logs`):

| File           | Logger            | Covers                                                                                                            |
| -------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------- |
| `database.log` | `vethuq.database` | schema creation and migrations, pre-migration backup, automatic/manual backups, restore/reset/repair, purges of removed sources/documents, integrity checks, connection/schema/write failures, search failures |
| `index.log`    | `vethuq.index`    | index worker start/exit, source scans, index runs (start/end/crash), OCR/extraction/indexing failures (file, page, engine, exception), every OCR worker thread (the thread name is on each line), stop/stale-lock handling |
| `ui.log`       | `vethuq.ui`       | the desktop app                                                                                                   |
| `cli.log`      | `vethuq.cli`      | each `vethuq` command's start and finish (exit code, duration) and CLI-level errors                                                             |

Each log rolls over at midnight: the previous day becomes `<name>.log.YYYY-MM-DD`
and the last `log_retention_days` (15 by default) days are kept, older files
are deleted. Verbosity is the `log_level` setting. Both are read when a
process first sets up a log; a change applies to processes started afterwards.

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
