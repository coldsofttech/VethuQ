<#
.SYNOPSIS
    Restore the full VethuQ workspace install (all packages + dev tools).

.DESCRIPTION
    A plain `uv sync` only syncs the current project, which drops the other workspace members
    (and can leave `vethuq` unrecognized). Run this after pulling changes that touch
    pyproject.toml or uv.lock. It also regenerates installer/shared/default-addons.txt.
#>

Set-Location (Join-Path $PSScriptRoot "..\..")
uv sync --all-packages --group dev
uv run python scripts/dev/sync_extras.py
