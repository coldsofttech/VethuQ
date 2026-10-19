# Changelog

All notable changes to `vethuq-background`.

## [Unreleased]

### Changed (installer)
- Start > Programs > VethuQ gets `VethuQ Background Service` (shows its status), `Start Background Service`, `Stop Background Service` and `Uninstall VethuQ Background Service`.

### Added
- The background service: works the index queue (`index.queue`), installs as a systemd user unit or a
  Windows service, pauses, resumes and stops cleanly; `vethuq background ...` commands.
