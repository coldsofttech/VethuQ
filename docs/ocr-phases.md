# Phased OCR indexing

Rotated text (a label on a drawing, a stamp at an angle) is often missed by a
single upright OCR pass, but reading every page at many angles is slow. OCR is
therefore split into phases, so a file is searchable after one fast pass while
the slower ones continue in the background.

## Phases and the `index_engine` setting

Angles are degrees counter-clockwise (`vethuq_core.ocr.Deepening.PHASE_ANGLES`):

| Phase | Angles | Reached with engine |
| --- | --- | --- |
| 1 | 0 | `quick` (default), `moderate`, `deep` |
| 2 | 90, 180, 270 | `moderate`, `deep` |
| 3 | every other multiple of 15 | `deep` |

Modes are cumulative. The setting is `index_engine` (`vethuq settings index
engine`, `client.settings.index.engine`) and is re-read each round, so changing
it mid-run takes effect without a restart.

JSON/YAML files have no OCR phases: they're read once, as text, so they're
complete after the quick pass and never appear in deeper-phase work or ETAs.

## Scheduling

`run_ocr_phased` (used by the background worker) loops:

1. **Quick first.** Run `run_ocr_batch` for every file that is new, changed or
   failed-and-retried. Repeat while it finds files, so files that arrive during
   a batch are picked up before anything deeper.
2. **Then deeper work** (`run_deepening_batch`): pages still short of the target
   phase, ordered by *next phase* so every page gets its moderate pass before any
   page gets a deep one.
3. **Yielding.** Between angle passes (never mid-pass) the batch checks for a stop
   request, and every `_QUICK_WORK_CHECK_SECONDS` for new files needing their
   quick pass. If there are any it returns; the loop handles them and resumes.

A file attempted once in a run is never retried by a later round of that run, and
a page whose deeper read fails is skipped for the rest of the run.

## Storage

`pdf_pages` and `image_pages` have two columns (schema v17):

- `ocr_phase` — highest phase fully done.
- `ocr_angles` — comma-separated angles already read.

Each angle's text is merged into `ocr_text` and saved as soon as it is read, so
pausing, stopping or a crash loses nothing. A re-indexed (modified) file's pages
are rewritten and start again at phase 1. Native-text PDF pages need no OCR and
are never deepened; duplicates reuse their original's pages.

## Merging and noise

Rotated reads add only what the page doesn't already say: a line contained in
existing text is dropped, and an existing line contained in a new one is replaced
by it (a word read partially at one angle and fully at another ends up once).
Lines from rotated passes below `_MIN_ROTATED_LINE_SCORE` are discarded, since odd
angles read drawing strokes as text far more often than upright reads do.

## Timing, metrics and ETA

Phase 1's timings stay on `document_index` (`started_at`, `completed_at`,
`indexed_at`). Each deeper phase gets one row per document in `document_phases`:

- `started_at` — the first page of the document starting real work for that phase.
- `completed_at` / `indexed_at` — the moment the document's last page reached the
  phase (its text for that phase is searchable).
- `duration_seconds`, `peak_memory_mb`, `cpu_percent` — accumulated across every
  page and every run that worked on it. Duration is active OCR time only, so a
  pause or giving way to a new file doesn't inflate it.

A document is folded into `processing_metrics` once, when it completes a phase.
That table is keyed by `(phase, file_type, size_bucket)`, so each phase keeps its
own averages - a deep pass takes far longer than a quick one, and blending them
would make every estimate wrong. The scheduler's memory/CPU budget check only
reads phase 1.

`vethuq index status` estimates the time left per phase: the documents a phase
still has to cover, by file type, times that phase's own average. The total is
their sum. A phase with no history yet has no estimate, and quick files not yet
indexed aren't counted towards deeper phases (how many pages they'll have, or
whether they're native text, isn't known until they are read).

A page's `confidence` is the average over its lines: a deeper pass that adds
lines pulls it toward the confidence of those lines, weighted by how many lines
the page already had. `confidence_metrics` (`vethuq stats`) is still only the
quick pass - a baseline - and isn't updated by deeper phases.
