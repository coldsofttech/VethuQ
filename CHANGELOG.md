# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial repository scaffold: uv workspace, `vethuq-core` package, CI, and pre-commit setup.
- Users can add folders and files as sources for OCR/indexing, from both the CLI (`vethuq source add/list/remove`) and the desktop UI toolbar.
- Registered sources are now OCR'd (English, PDF/PNG/JPEG) and indexed into the local database — via `vethuq index run` in the CLI, or automatically in the background in the desktop app.
- PDFs with real, selectable text are now indexed directly from that text instead of being run through OCR, which is faster and more accurate; OCR now only runs on scanned pages or scanned regions within an otherwise digital page.

### Fixed

- Re-indexing a document (e.g. after removing and re-adding its source) no longer leaves stale page text from the previous run alongside the new results.
- `vethuq index run` now also checks already-indexed sources for files added since the last run, instead of only ever looking at sources it hasn't touched yet.
