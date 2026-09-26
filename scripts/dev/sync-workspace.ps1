<#
.SYNOPSIS
    Restore the full VethuQ workspace install (all packages + dev tools).

.DESCRIPTION
    Plain `uv sync` only syncs the current project, not the whole workspace -
    it silently drops the other workspace members (vethuq-core, vethuq-cli,
    vethuq-ui), which is why `vethuq` can stop being a recognized command.
    Run this any time that happens, or after pulling changes that touch
    pyproject.toml/uv.lock.
#>

Set-Location (Join-Path $PSScriptRoot "..\..")
uv sync --all-packages --group dev
