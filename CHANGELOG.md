# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Fixed

- Re-indexing a document (e.g. after removing and re-adding its source) no longer leaves stale page text from the previous run alongside the new results.
- `vethuq index run` now also checks already-indexed sources for files added since the last run, instead of only ever looking at sources it hasn't touched yet.
- Commands that don't do OCR (e.g. `vethuq settings gpu status`) no longer print unrelated OCR-engine startup messages.
