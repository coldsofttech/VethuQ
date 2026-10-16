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
| `search QUERY` | `--engine`, `--normalize NAME=LEVEL`, `--option ENGINE.OPTION=VALUE`, `--language`, `--limit`, `--export FILE`, `--format json\|html` |
| `search-index` / `search-engines` | `status`, `rebuild` / `list`, `normalizers` |
| `file-types`, `languages`, `tiers`, `credits`, `metrics`, `ocr`, `db`, `logs`, `stats`, `updates`, `policy`, `addons` | Look at and manage what each name says |
| `settings` | Show and change settings, as a hierarchy (below) |

### Exporting a list

The listing commands take `--export FILE` and `--format json|html` and write the list to a file instead of printing it
(`--format` alone is an error; without it the saved format is used, `vethuq settings search export-format`):

    vethuq source list --export sources.html --format html
    vethuq source files 1 --detailed --export files.html --format html
    vethuq addons list --export addons.json
    vethuq search "invoice" --export found.html --format html

They are `source list|files`, `index queue list|history|jobs`, `search-engines list|normalizers`, `file-types list`,
`languages list`, `tiers list`, `credits history`, `ocr models list|phases|engines`, `stats show|failures|low-confidence`
and `addons list`. The HTML page has filters (a dropdown per column that has more than one value), a live
"Showing X of Y", and prints with every row open.

## Updates and notices

VethuQ checks a signed policy file (at most about once a day) to learn the newest version, notices and feature switches. It makes no request until something asks for one, and local work is never blocked by it.

    vethuq update                 # is a newer VethuQ out? prints the exact upgrade steps for how it is installed
    vethuq update --no-check      # the same from what is already saved, with no request
    vethuq updates status         # what was last found out
    vethuq updates check --force  # look now
    vethuq policy notices         # the notices active now
    vethuq policy show            # the policy in force

`vethuq update` names how VethuQ is installed (installer, pipx, virtual environment, externally-managed Python, or pip) and prints the command that upgrades it, including add-ons that have a newer version. It changes nothing: VethuQ never upgrades itself inside the running command.

After a command, when a newer version exists, one line is printed to stderr (for example `VethuQ 2.0.0 is available (you have 1.5.0). Run: vethuq update`), followed by any active notice with its severity and link. It never asks a question, and is not printed when output is piped or redirected, with `--json`, with `--help`/`--version`, or when the check is off.

| To | Do |
|---|---|
| Check and offer (default) | `vethuq settings updates check on` |
| Only tell me | `vethuq settings updates check notify-only` |
| Never check | `vethuq settings updates check off`, or set `VETHUQ_UPDATE_CHECK=off` (also `0`, `false`, `no`, `disable`, `disabled`), which wins over the setting |
| Hide the notice for a day | `vethuq settings updates snoozed-until` (see `vethuq settings show`) |

Checking for updates fetches one small signed file (the policy) from a static web host. The host sees your IP address and the request's fixed identity, `VethuQ-policy/1`. **Your VethuQ version is not sent**: the comparison happens on your computer. No telemetry is added, and GitHub Pages gives no access logs to us.

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

`vethuq index submit` and `vethuq index queue list|show|cancel` follow queued requests. With `vethuq-background` installed, `vethuq background install|start|stop|status ...` appears (packages add commands through the `vethuq.cli` entry-point group), and while its service runs, `index run|restart|reindex` queue their work (`--one-off` runs one here).

Errors print `Error: ...` and `What to do: ...` and exit with the error's own code.
