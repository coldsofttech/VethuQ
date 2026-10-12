# Changelog

All notable changes to `vethuq-desktop`.

## [Unreleased]

### Added
- The desktop host: starts the API on `127.0.0.1` on a free port, opens a frameless pywebview window
  (WebView2 on Windows) on it, and shuts the server down when the window closes. `--no-window`
  serves the interface for a browser or for tests.
