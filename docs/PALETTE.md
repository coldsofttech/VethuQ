# Color palette

One set of design tokens drives every surface: the HTML search export, the CLI, and (later)
a web layer. The desktop UI is drawn by `sv_ttk`, whose accent can't be set from outside, so the
palette is built around it: `primary` is exactly `sv_ttk`'s light (`#005FB8`) and dark (`#57C8FF`)
accent.

The source of truth is [`palette.json`](../packages/vethuq-core/src/vethuq_core/branding/palette.json),
read through `vethuq_core.branding.Palette`. It has a `light` and a `dark` scheme that define the
same tokens.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `primary` / `primary-hover` / `primary-soft` | `#005FB8` / `#004A91` / `#E3EEF9` | `#57C8FF` / `#8AD8FF` / `#16384A` | Links, primary actions, selected-row tint |
| `on-primary` | `#FFFFFF` | `#1A1A1A` | Text on a `primary` fill |
| `bg` / `surface` / `surface-alt` | `#FAFAFA` / `#FFFFFF` / `#F0F3F7` | `#1C1C1C` / `#2B2B2B` / `#323232` | Page, panels, table headers |
| `border` / `border-soft` | `#DDE3EA` / `#EEF2F6` | `#3A3A3A` / `#303030` | Dividers |
| `text` / `text-muted` | `#1A1A1A` / `#5B6B7D` | `#F2F2F2` / `#A8B3BF` | Body and secondary text |
| `accent` | `#0B7F73` | `#2FC4B2` | Teal: GPU on, commands, secondary emphasis |
| `highlight` / `on-highlight` | `#FFD866` / `#1A1A1A` | `#FFD866` / `#1A1A1A` | Search-match marker and its text |
| `success` | `#1B7F4B` | `#4CC38A` | Indexed, finished |
| `warning` / `warning-bg` / `warning-fill` | `#8A5A00` / `#FFF4D6` / `#F2B01E` | `#F2B01E` / `#3A2E0B` / `#F2B01E` | Paused, duplicates (`warning-fill` is for icons) |
| `danger` | `#C42B31` | `#FF7B72` | Errors, delete, stop |

Every text pairing is held to WCAG AA (4.5:1) by `tests/branding/test_palette.py`, so a palette
edit that breaks readability fails CI.

## Where it is used

- **HTML export:** `Palette.css_variables()` emits `--vq-<token>` custom properties (light, plus a
  `prefers-color-scheme: dark` block) into the page; `export.css` uses only `var(--vq-…)`, never a
  literal color.
- **CLI:** `vethuq_cli.theme.Theme` builds Rich styles from the dark scheme (terminals are mostly
  dark). Use `Theme.ERROR`, `Theme.OK`, `Theme.VALUE` and friends rather than named ANSI colors.
- **Icons:** drawn from the same tokens. Role: actions `primary`, destructive `danger`, PDF
  `danger`, images `accent`, folders/files `warning-fill` with a `warning` outline, GPU `accent`
  (on) or a neutral grey (off).
- **Web (later):** reuse `Palette.css_variables()` unchanged.

## Changing it

Edit `palette.json` and keep both schemes in step. The tests check that they define the same
tokens, that every value is an uppercase `#RRGGBB`, and that the text pairings stay readable.
