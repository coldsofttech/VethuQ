# Changelog

All notable changes to `vethuq-addon-api` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

The add-on API version (`API_VERSION`) is 0.4.0.

### Added (API 0.4.0)
- Processing tiers: `TierSpec`, `Addon.processing_tiers()`, and the executor contract (`OcrExecutor`,
  `OcrRequest`, `JobState`). A tier decides where pages that need OCR are read; a synchronous
  executor implements `recognize`, an asynchronous one `submit`, `poll`, `collect` and `cancel`.
- `Host.licence_tokens()`: the installed add-on licences by add-on id, for tiers that read pages
  elsewhere and have the licences checked there.
- Testing: `FakeExecutor`; `FakeHost.licences`.

### Added (API 0.3.0)
- File types: `FileTypeSpec`, `Addon.file_types()`, and the reader contract (`DocumentReader`,
  `ReadPage` (with the page size in points), `Region`, `UnreadableFileError` and its subclasses,
  `extended_path`).
- OCR engines: `OcrEngineProvider` (create an engine, name and fetch its models), `OcrEngine`,
  `OcrResult`, `OcrModelSpec`, `Addon.ocr_engines()`.
- OCR phases: `OcrPhaseSpec` and `Addon.ocr_phases()`.
- Testing: `FakeEngine` and `FakeReader`.

### Added (API 0.2.0)
- `LanguageSpec` and `Addon.languages()`: a language add-on tells VethuQ which languages it provides
  (id, label, native label, script, default, availability and the reason when unavailable, and an
  `ocr` mapping for later).

### Added (API 0.1.0)
- The first add-on API (`major.minor.patch` like the policy's `addon_api` range): `Addon`,
  `Manifest`, `Hook` (`on_open`, `before_migration`), `MigrationInfo`, the `Host` protocol,
  `AddonError` / `AddonLicenceError`, and `testing.FakeHost`.
