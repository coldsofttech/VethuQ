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
- You can now search indexed content from the CLI with `vethuq search <content>`, which highlights the match in a snippet of surrounding text; how much surrounding text is shown is configurable with `vethuq settings search snippet set/show`.
- The desktop app now has a search screen (a search box and a results list showing each match's file), and its toolbar has been redesigned as a ribbon with a Windows 11-styled look.
- Search results and Sources list columns can now be resized, and show hover tooltips for text that's cut off.
- The Home ribbon now has quick actions for adding a folder/file, viewing the source list, and pausing/stopping/deleting a selected source.
- The Sources list now shows a file/folder icon, capitalized status, and how many files have been processed per source.
- Viewing a source's run history now opens alongside the source list instead of a separate popup window.
- Dialogs and right-click menus in the desktop app are now styled to match its Windows 11 theme.
- A removed source is now fully deleted from the database (not just hidden) after it's been removed for a while — 7 days by default, configurable with `vethuq settings index removed-retention set/show`.
- Indexed documents now record their file size.
- VethuQ now tracks running averages of OCR duration, confidence, and text-source mix (native/OCR/mixed) per file type.
- `vethuq index status`'s ETA is now based on historical average OCR duration per file type, rather than this run's own pace, so it's available even before any file in the current run has finished.

### Fixed

- Re-indexing a document (e.g. after removing and re-adding its source) no longer leaves stale page text from the previous run alongside the new results.
- `vethuq index run` now also checks already-indexed sources for files added since the last run, instead of only ever looking at sources it hasn't touched yet.
- Commands that don't do OCR (e.g. `vethuq settings gpu status`) no longer print unrelated OCR-engine startup messages.
- Searching no longer returns matches from files whose source has been removed.
