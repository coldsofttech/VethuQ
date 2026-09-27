# VethuQ Desktop

VethuQ Desktop is the point-and-click version of VethuQ — everything the
`vethuq` CLI does, without needing to type commands. Windows only for now.

## Install

Download `VethuQ-Setup.exe` from the
[latest release](https://github.com/coldsofttech/VethuQ/releases) and run
it. It installs VethuQ and adds a Start Menu (and optional desktop)
shortcut — no Python or other setup needed.

## Adding sources

Use the toolbar's **Add Folder**/**Add File** buttons to register files or
folders — folders are always indexed recursively. Indexing then starts
automatically in the background; there's no separate "run" step like the
CLI.

Manage what's registered from **Settings > Sources**, which also lets you
remove a source.

## Watching indexing progress

The status bar at the bottom shows indexing progress while sources are
being processed. If a file's content exactly matches one you've already
indexed anywhere across your sources, it's recognized as a duplicate and
linked to the original instead of being OCR'd again — duplicates still
show up in search results, marked as such.

## Searching

Once sources are indexed, search from the toolbar. Each result shows the
file it was found in and a snippet of matching text with your search term
highlighted.

## Settings

The **Settings** menu covers:
- **Sources** — add, view, and remove registered sources.
- **GPU** — turn GPU-accelerated OCR on or off (off by default; only
  useful if your machine has a supported GPU).
- Search snippet length and other preferences shared with the CLI.

## Relationship to the CLI/library

VethuQ Desktop is built on the same `vethuq` engine as the CLI and Python
library (see [docs/CLI.md](CLI.md) and [docs/PYTHON_API.md](PYTHON_API.md))
— sources, indexing, and search all share the same local database, so
adding a source in the desktop app makes it available to the CLI too, and
vice versa.
