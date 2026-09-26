# VethuQ
VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

## Compatibility

The `vethuq` CLI works on both Windows and Linux. The desktop app is Windows-only.

## Usage

Add a file or folder as a source, then index it so its text becomes searchable:

```bash
vethuq source add ./path/to/folder-or-file
vethuq index run
```

`vethuq index run` starts OCR (English, currently supporting PDF, PNG, and JPEG files) in the background and returns right away — including picking up new files added to a source you've already indexed. Check on it with `vethuq index status`, or `vethuq index status <source>` for a detailed per-file breakdown. You can pause, resume, or stop a run with `vethuq index pause` / `resume` / `stop`, see past runs with `vethuq index history`, and retry just the files that failed with `vethuq index restart`.

In the desktop app, add sources from the toolbar — indexing then happens automatically in the background, no extra step needed.

Once your files are indexed, search them from the CLI:

```bash
vethuq search "invoice total"
```

Each result shows the file it was found in and a snippet of the matching text, with your search term highlighted. How much surrounding text is shown can be adjusted with `vethuq settings search snippet set <characters>`.

OCR runs on CPU by default. If your machine has a supported GPU, you can turn GPU use on via `vethuq settings gpu enable`, or from the desktop app's **Settings** menu.

See [docs/CLI.md](docs/CLI.md) for the full command reference.
