# Desktop app icon palette

Color reference for the icon assets used by the desktop app
(`packages/vethuq-ui/src/vethuq_ui/assets/icons/`), generated via the
`vethuq-icons` skill (`.claude/skills/vethuq-icons/`). Colors are drawn from
Microsoft's Fluent/Windows 11 accent palette so they read as native next to
the app's `sv_ttk` Windows 11 theme, and are chosen so no two icons in
either group share a hue.

## File-type badges

Shown next to each match in the search results list (`get_file_icon` in
`vethuq_ui/icons.py`).

| Icon | Color | Hex | Status |
|---|---|---|---|
| PDF | red | `#FF0000` | generated (`pdf.png`) |
| PNG | blue | `#0078D4` | generated (`png.png`) |
| JPG | orange | `#F7630C` | generated (`jpg.png`) |
| default | gray | `#737373` | pending |

## Ribbon action icons

Shown on the Home/Settings ribbon buttons (`_build_menubar` in `app.py`).

| Icon | Color | Hex | Status |
|---|---|---|---|
| Search | violet | `#8764B8` | generated (`search.png`) |
| Sources | gold | `#FFB900` | pending |
| GPU | teal | `#00B294` | generated (`gpu.png`) |

## Regenerating

Feed these colors into a `vethuq-icons` manifest entry per icon (SVG source
+ `color`) and run `.claude/skills/vethuq-icons/generate_icons.py` — see
that skill for the manifest format and full workflow.
