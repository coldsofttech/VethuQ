# VethuQ
VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

## Usage

Add a file or folder as a source, then index it so its text becomes searchable:

```
vethuq source add ./path/to/folder-or-file
vethuq index run
```

`vethuq index run` processes every source that hasn't been indexed yet, running OCR (English, currently supporting PDF, PNG, and JPEG files) and storing the extracted text locally.

In the desktop app, add sources from the toolbar — indexing then happens automatically in the background, no extra step needed.

See [docs/CLI.md](docs/CLI.md) for the full command reference.
