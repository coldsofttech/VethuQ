<#
.SYNOPSIS
    Restore the full VethuQ workspace install (all packages + dev tools).

.DESCRIPTION
    Plain `uv sync` only syncs the current project, not the whole workspace -
    it silently drops the other workspace members (vethuq-core, vethuq-cli,
    vethuq-ui), which is why `vethuq` can stop being a recognized command.
    Run this any time that happens, or after pulling changes that touch
    pyproject.toml/uv.lock. It also removes anything installed via a bare
    `uv pip install` (e.g. reportlab/svglib for the icons skill) since that
    isn't tracked in the lockfile - pass -Icons to keep those too instead of
    reinstalling them with `uv pip install` afterwards.

.PARAMETER Icons
    Also sync the opt-in `icons` dependency group (svglib/reportlab, used by
    .claude/skills/vethuq-icons/generate_icons.py).
#>

param(
    [switch]$Icons
)

Set-Location (Join-Path $PSScriptRoot "..\..")
if ($Icons) {
    uv sync --all-packages --group dev --group icons
} else {
    uv sync --all-packages --group dev
}
