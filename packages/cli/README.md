# vethuq-cli

The `vethuq` command line, built on the public `vethuq` API (never its internals).

    pip install vethuq-cli
    vethuq source add ~/Documents
    vethuq index run
    vethuq search "invoice" --engine like

With `vethuq-interactive-cli` installed, `vethuq` with no command (in a terminal) opens the interactive shell, and `--interactive` forces it.

Every command takes the global `--json` (print JSON) and `--db FILE`. With no command it prints help.

| Group | What it does |
|---|---|
| `source` | `add`, `list`, `files`, `remove`, `purge`, `set-languages`, `export` |
| `index` | `run`, `restart`, `reindex source\|file`, `status [--live]`, `pause`, `resume`, `stop`, `clear-stale`, `history`, `jobs`, `collect` |
| `search QUERY` | `--engine`, `--normalize NAME=LEVEL`, `--option ENGINE.OPTION=VALUE`, `--language`, `--limit`, `--export FILE` |
| `search-index` / `search-engines` | `status`, `rebuild` / `list`, `normalizers` |
| `file-types`, `languages`, `tiers`, `credits`, `metrics`, `ocr`, `db`, `logs`, `stats`, `updates`, `policy`, `addons` | Look at and manage what each name says |
| `settings` | Show and change settings, as a hierarchy (below) |

## Settings

    vethuq settings show
    vethuq settings index workers auto
    vethuq settings index stale-lock disable
    vethuq settings ocr gpu true
    vethuq settings search normalize case ignore
    vethuq settings search fuzzy threshold loose         # an engine's options: engine, then option
    vethuq settings search noise-fuzzy noise high
    vethuq settings addons backup interval-minutes 720   # an add-on's own settings

No value shows the setting; `--reset` puts the default back. The hierarchy is read from the settings
the client has and from the installed engines and add-ons, so new settings and engine options appear
without changes here.

## Add-on commands

An installed add-on may add commands (`Addon.cli()`, add-on API 0.11.0): `vethuq backup create`,
`vethuq autoscale licence set TOKEN`, `vethuq telugu licence show` ... They appear only while the
add-on is installed. `vethuq addons list` shows what is installed.

Errors print `Error: ...` and `What to do: ...` and exit with the error's own code.
