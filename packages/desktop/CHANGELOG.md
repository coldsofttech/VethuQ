# Changelog

All notable changes to `vethuq-desktop`.

## [Unreleased]

### Added (installer)
- `vethuqd.exe`, the frozen desktop application (PyInstaller, no console), and `VethuQ-Desktop-Setup.exe` (Inno Setup), which installs it into the command line's folder. Released with tag `vethuq-desktop-vX.Y.Z` (`release-desktop.yml`); built by `scripts/release/release.py --desktop`.

### Added (opening at the place)
- `open_file(path, page, line, column)` opens a file in its default application at a page or line where it can (browsers, Adobe/Foxit/Sumatra PDF, VS Code, Notepad++, Sublime) and otherwise at the top, returning `{opened, jumped, hint}`.

### Added
- The window can open a file in its own application (`open_file`).
- The window holds back a close while indexing runs in this application (the interface asks first),
  accepts one file or folder dropped on it, opens a file picker, and shows a file in Explorer.
- The desktop host: starts the API on `127.0.0.1` on a free port, opens a frameless pywebview window
  (WebView2 on Windows) on it, and shuts the server down when the window closes. `--no-window`
  serves the interface for a browser or for tests.
