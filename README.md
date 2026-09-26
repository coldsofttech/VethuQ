# VethuQ
VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

## Usage

Add a file or folder as a source, then index it so its text becomes searchable:

```
vethuq source add ./path/to/folder-or-file
vethuq index run
```

`vethuq index run` runs OCR (English, currently supporting PDF, PNG, and JPEG files) and stores the extracted text locally — including picking up new files added to a source you've already indexed.

In the desktop app, add sources from the toolbar — indexing then happens automatically in the background, no extra step needed.

Once your files are indexed, search them from the CLI:

```
vethuq search "invoice total"
```

Each result shows the file it was found in and a snippet of the matching text, with your search term highlighted. How much surrounding text is shown can be adjusted with `vethuq settings snippet set <characters>`.

OCR runs on CPU by default. If your machine has a supported GPU, you can turn GPU use on via `vethuq settings gpu enable`, or from the desktop app's **Settings** menu.

See [docs/CLI.md](docs/CLI.md) for the full command reference.
