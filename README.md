# VethuQ
VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

## Compatibility

The `vethuq` CLI and Python library work on both Windows and Linux. The desktop app is Windows-only.

## Install

Not comfortable with the command line? Download the desktop app installer instead — see [docs/DESKTOP.md](docs/DESKTOP.md).

For the CLI or library, install with pip (Python 3.11+):

```bash
pip install vethuq
```

This gives you both the `vethuq` command (used throughout this page — full reference in [docs/CLI.md](docs/CLI.md)) and the `vethuq` Python library:

```python
import vethuq

client = vethuq.Vethuq()
client.sources.add("./path/to/folder-or-file")
```

See [docs/PYTHON_API.md](docs/PYTHON_API.md) for the full library reference.

## Usage

Run `vethuq` on its own to open an interactive menu for Search, Sources, Index, and Settings — handy if you'd rather navigate than remember flags. Everything below also works as a direct command.

Add a file or folder as a source, then index it so its text becomes searchable:

```bash
vethuq source add ./path/to/folder-or-file
vethuq index run
```

`vethuq index run` starts OCR (English, currently supporting PDF, PNG, JPEG, JSON, and YAML files — JSON/YAML are read as text, no OCR needed) in the background and returns right away — including picking up new files added to a source you've already indexed, re-indexing any file whose content has changed since, recognizing a file that's simply been renamed or moved (no re-OCR needed), and flagging a file that's gone missing from the source for cleanup after a retention period. Check on it with `vethuq index status`, or `vethuq index status <source>` for a detailed per-file breakdown. You can pause, resume, or stop a run with `vethuq index pause` / `resume` / `stop`, see past runs with `vethuq index history`, and retry just the files that failed with `vethuq index restart`.

If a file's content exactly matches a file you've already indexed — anywhere across your sources, not just the same one — VethuQ recognizes it as a duplicate and skips OCR'ing it again, linking it to the original instead. Duplicates still show up in `vethuq index status` and in search results, marked as a duplicate of the original file.

In the desktop app, add sources from the toolbar — indexing then happens automatically in the background, no extra step needed.

Once your files are indexed, search them from the CLI:

```bash
vethuq search "invoice total"
```

Each result shows the file it was found in and a snippet of the matching text, with your search term highlighted. How much surrounding text is shown can be adjusted with `vethuq settings search snippet set <characters>`. While viewing results, press `e` to export them to a file (you'll be asked for a filename and format), or `q` to close without exporting.

Text that's rotated or sideways (labels on a drawing, a photographed page, a stamp at an angle) is found in extra passes that run in the background. Every file is indexed quickly first, so it's searchable right away, and deeper passes then add more text while indexing carries on. Choose how thorough they are with `vethuq settings index engine set <quick|moderate|deep>` — `quick` (the default) reads upright text only, `moderate` also looks at 90°, 180° and 270° rotations, and `deep` also tries every 15°. New files always get their quick pass before any deeper work continues.

OCR runs on CPU by default. If your machine has a supported GPU, you can turn GPU use on via `vethuq settings gpu enable`, or from the desktop app's **Settings** menu.

Curious how indexing has been performing? `vethuq stats show` displays processing and confidence statistics — how long OCR takes and how confident the results are, per file type and text source. `vethuq stats reset` clears them if you want a fresh baseline.

See [docs/CLI.md](docs/CLI.md) for the full command reference, [docs/PYTHON_API.md](docs/PYTHON_API.md) for the library, or [docs/DESKTOP.md](docs/DESKTOP.md) for the desktop app.
