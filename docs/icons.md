# Desktop app icon palette

Color reference for the icon assets used by the desktop app
(`packages/vethuq-ui/src/vethuq_ui/assets/icons/`), generated via the
`scripts/dev/generate_icons.py`. Colors are drawn from
Microsoft's Fluent/Windows 11 accent palette so they read as native next to
the app's `sv_ttk` Windows 11 theme, and are chosen so no two icons in
either group share a hue.

## Regenerating

Feed these colors into a manifest entry per icon (SVG source + `color`) and
run `scripts/dev/generate_icons.py` — see its module docstring for the
manifest format and full workflow.
