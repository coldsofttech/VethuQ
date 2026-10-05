# VethuQ Desktop

VethuQ Desktop is the point-and-click version of VethuQ — everything the
`vethuq` CLI does, without needing to type commands. Windows only for now.

## Install

Download `VethuQ-Setup.exe` from the
[latest release](https://github.com/coldsofttech/VethuQ/releases) and run
it. By default it installs both VethuQ Desktop and the `vethuq` CLI, adds a
Start Menu (and optional desktop) shortcut, and offers to add VethuQ to your
PATH so `vethuq` works from any terminal — no Python or other setup needed.
On the "Select Components" step you can instead choose Desktop only or CLI
only; the shared runtime that both rely on installs either way.

The installer also asks whether to install **for all users** or **for the
current user only**. All users needs administrator rights (Windows asks for
confirmation) and installs to `C:\Program Files\VethuQ`; current user needs
no administrator rights and installs to `%LOCALAPPDATA%\Programs\VethuQ`.
The CLI, the PATH option and uninstalling work the same either way (the PATH
entry is added to, and removed from, the system or your own user PATH to
match).

### Background service

The installer's **Run indexing through a background service** option (all-users installs only, since creating a Windows service needs administrator rights; silent installs accept `/TASKS=backgroundservice`) installs `VethuQBackground`, a Windows service that runs `vethuq-worker.exe --service`. With it, indexing carries on when the app is closed and starts with Windows. A current-user install can add it later from the app (**Index > Service**) or with `vethuq background-service install`; both ask for administrator permission. Setup stops the service while it replaces files and starts it again; uninstalling removes it. See [CLI.md](CLI.md#background-service).

## Adding sources

Use the toolbar's **Add Folder**/**Add File** buttons to register files or
folders — folders are always indexed recursively. Indexing then starts
automatically in the background; there's no separate "run" step like the
CLI.

Manage what's registered from **Settings > Sources**, which also lets you
remove a source.

**Index > Service** installs, uninstalls, starts, stops, restarts, pauses and resumes the background service, and shows its state and how many runs are queued. While the service is installed the app queues its indexing for it (rescanning at most once a minute) and closing the app does not stop the run.

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

## Languages

The installer has a **Languages** page. English is always installed; tick Telugu to add it (silent installs: `/LANGS=en,te`). If Windows has no Telugu font (Nirmala UI, Gautami or Vani), the installer also copies Noto Sans Telugu (SIL OFL) into the app's `fonts` folder. The app loads it for itself only; nothing is installed into Windows. Telugu OCR models download the first time they are needed, or ahead of time with `vethuq ocr models download`.
