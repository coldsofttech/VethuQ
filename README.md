# VethuQ
VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

## Usage

Add a file or folder as a source, then index it so its text becomes searchable:

```
vethuq source add ./path/to/folder-or-file
vethuq index run
```

`vethuq index run` starts OCR (English, currently supporting PDF, PNG, and JPEG files) in the background and returns right away — including picking up new files added to a source you've already indexed. Check on it with `vethuq index status`, or `vethuq index status <source>` for a detailed per-file breakdown. You can pause, resume, or stop a run with `vethuq index pause` / `resume` / `stop`, and see past runs with `vethuq index history`.

In the desktop app, add sources from the toolbar — indexing then happens automatically in the background, no extra step needed.

OCR runs on CPU by default. If your machine has a supported GPU, you can turn GPU use on via `vethuq settings gpu enable`, or from the desktop app's **Settings** menu.

See [docs/CLI.md](docs/CLI.md) for the full command reference.
