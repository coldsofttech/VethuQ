# VethuQ
VethuQ — open-source document intelligence and evidence infrastructure for search, retrieval, structure, metadata, relationships, and AI-ready document access.

## Development

If `vethuq` is not found after a plain `uv sync`, restore the whole workspace with
`uv run python scripts/dev/sync.py` (same as `uv sync --all-packages --group dev`).

## User interface (Windows)

`web/` is the React + Fluent UI interface (with `viewers/text` (with its CSS colouring), `viewers/table`, `viewers/code`, `viewers/feed`, `viewers/email` and `viewers/markdown`, `viewers/html` and `viewers/image`, the viewers its search preview uses, and `keyboards/en`, `keyboards/es`, `keyboards/fr`, `keyboards/hi`, `keyboards/te` and `keyboards/ur` (on `keyboards/shared`), its on-screen English, Spanish, French, Hindi, Telugu and Urdu keyboards), `packages/api` the Flask API it talks to and
`packages/desktop` the pywebview host that shows it in a window (see `packages/desktop/README.md`).

    cd web && npm ci && npm run build
    uv run vethuq-desktop
