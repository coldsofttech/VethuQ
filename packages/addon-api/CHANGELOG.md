# Changelog

All notable changes to `vethuq-addon-api` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- The first add-on API (version 0.1.0, `major.minor.patch` like the policy's `addon_api` range): `Addon`, `Manifest`, `Hook` (`on_open`, `before_migration`),
  `MigrationInfo`, the `Host` protocol, `AddonError` / `AddonLicenceError`, and `testing.FakeHost`.
