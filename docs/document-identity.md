# Document identity and duplicate originals

**Identity.** A document's identity is its content: files with the same SHA-256 link to one
logical `documents` row. Re-indexing, removing and re-adding a source, and creating or scanning
files in a different order all resolve to the same groups.

**Original.** When several files share content, the original is the earliest-indexed
`document_index` row (lowest id). Within a run, `ContentGate` makes that the first file in the
sorted run order: a later identical file waits for it, so worker count and thread timing never
change which file is the original or how many OCR passes happen. Across runs, the earliest
already-indexed file stays the original.

Tests: `packages/vethuq-core/tests/ocr/test_identity.py` and `test_determinism.py`.
