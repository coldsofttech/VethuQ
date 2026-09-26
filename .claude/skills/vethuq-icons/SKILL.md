---
name: vethuq-icons
description: Generate every icon PNG used across the vethuq-ui desktop app - ribbon action icons (Search, Sources, GPU, ...) and file-type badges (PDF, PNG, JPG, default) - from SVG sources (e.g. Bootstrap Icons) with color enhancements, and wire the app to load them.
trigger: /vethuq-icons
---

# /vethuq-icons

Generates every icon PNG the VethuQ desktop app (`packages/vethuq-ui`) uses
in place of a hand-drawn shape or a Unicode glyph, and saves them as static
assets checked into the repo. That currently covers two kinds:

- **Ribbon action icons** — the icon shown on each ribbon button in
  `_build_menubar` (`app.py`): Search (Home tab), Sources and GPU (Settings
  tab). These are currently a Unicode character embedded in the button's
  `text` (e.g. `"\N{LEFT-POINTING MAGNIFYING GLASS}\nSearch"`) — replace
  that with a real icon image.
- **File-type badge icons** — the small icon shown next to each result in
  the search results list (`get_file_icon` in
  `packages/vethuq-ui/src/vethuq_ui/icons.py`): PDF, PNG, JPG, and a
  default/fallback. These used to come from the OS's registered Shell icon
  at runtime; the app should look the same on every machine regardless of
  what's installed there or how that machine's icon theme looks, hence
  static, checked-in assets instead.

## When to use this

- The user asks to (re)generate, redesign, or restyle any icon in the
  desktop app — ribbon buttons or file-type badges.
- A new ribbon command is added (a new tab/group/button in
  `_build_menubar`) and needs its own icon.
- A new file type is added to what `vethuq index run` can OCR/index (check
  `packages/vethuq-core/src/vethuq_core/ocr.py` for the current supported
  extensions), and it needs its own badge icon instead of falling back to
  the default one.

## Inputs this skill accepts

Each icon comes from an SVG source plus a color enhancement, not from
scratch. Per icon needed (`search`, `sources`, `gpu`, `pdf`, `png`, `jpg`,
`default`, ...), the user gives you one of:

1. **An SVG file path or pasted SVG markup** they already have (e.g. a
   Bootstrap Icons file like `filetype-pdf.svg` they've downloaded or that
   sits in a local `node_modules/bootstrap-icons/icons/` install) — use it
   as-is.
2. **A URL to a specific icon**, e.g.
   `https://icons.getbootstrap.com/icons/file-earmark-pdf-fill/` — fetch it
   with `WebFetch`, asking for the exact `<svg>...</svg>` markup (including
   `viewBox` and every `<path d="...">`), verbatim. This is fine precisely
   *because* the user gave you this URL themselves — the "never guess a
   URL" rule is about not inventing/fabricating one (e.g. constructing a
   `getbootstrap.com/icons/<guessed-slug>/` yourself from a description),
   not about refusing a URL that's already in front of you.

   `WebFetch` pipes the page through a summarizing model, so treat the
   returned markup as *probably* exact rather than guaranteed byte-for-byte
   - it has matched a user's own pasted copy exactly in practice, but dense
   path data is exactly the kind of content a summarizer could subtly
   mangle without it being obvious from the text alone. The real check is
   empirical, not textual: after generating the PNG (see below), look at
   it - a corrupted path usually renders as visibly broken/garbled
   geometry, not a plausible-looking icon that's subtly wrong.
3. **A plain-language description/comment** naming the icon they want, with
   neither a file nor a URL. Don't invent a Bootstrap Icons URL yourself in
   this case - ask the user for one of the above instead.

Also ask for, if not already given:

- **The accent color(s)** per file type for the "color enhancement" pass
  (e.g. PDF red, PNG green, JPG blue — match whatever the user wants,
  don't assume the old badge colors from the retired Shell-icon fallback
  still apply).
- **Which extensions need an icon right now.** As of this writing that's
  `.pdf`, `.png`, `.jpg`/`.jpeg`, plus one `default` icon for everything
  else — confirm against `_indexed_pages` / OCR support in `vethuq-core`
  in case that's grown since.
- **Whether a dark-theme variant is needed.** The app currently always
  calls `sv_ttk.set_theme("light")`; if/when a dark mode toggle exists,
  icons may need a second set that reads well on a dark background.

## Generating the icons

The actual SVG-to-PNG conversion is **not something to improvise per
invocation** — it's a tested, committed script:
`.claude/skills/vethuq-icons/generate_icons.py`. This skill's own job at
this step is just to gather each icon's inputs (SVG + color + size) into a
manifest JSON and run that script — see the module docstring in
`generate_icons.py` for the exact manifest format.

```bash
uv run python .claude/skills/vethuq-icons/generate_icons.py --manifest <manifest.json>
```

`svglib`, `reportlab`, and `pillow` are pinned in the repo root
`pyproject.toml`'s `dev` dependency-group (run `uv sync` if they're
missing), so no `--with` flags are needed. That pinned set is deliberate,
not a suggestion to swap freely:

- `cairosvg` was tried first and fails on a plain Windows box — it needs
  the native Cairo library, which isn't installed and isn't a pip package.
- `svglib` + `reportlab` render SVG with no native system dependency, but
  **reportlab must stay pinned to `3.6.13`** — newer reportlab's PNG
  backend (`renderPM`) requires `rlPyCairo`, which hits the same native
  Cairo wall. 3.6.13 is the last line with a self-contained renderer.
- None of these three are runtime deps of the app (only of this script),
  so they live in the root `dev` group, not
  `packages/vethuq-ui/pyproject.toml`.

The script also solves a real problem you'd hit rebuilding this from
scratch: reportlab 3.6.13's PNG output has no alpha channel (opaque white
background), so it recovers transparency itself — precisely, from the
known glyph color, when the manifest gives one (do this whenever the
source is a flat single-color glyph, which Bootstrap Icons and similar
sets are); via a cruder near-white cutoff otherwise.

The manifest writes to (default) or an explicit `--out-dir`:

```
packages/vethuq-ui/src/vethuq_ui/assets/icons/search.png
packages/vethuq-ui/src/vethuq_ui/assets/icons/sources.png
packages/vethuq-ui/src/vethuq_ui/assets/icons/gpu.png
packages/vethuq-ui/src/vethuq_ui/assets/icons/pdf.png
packages/vethuq-ui/src/vethuq_ui/assets/icons/png.png
packages/vethuq-ui/src/vethuq_ui/assets/icons/jpg.png
packages/vethuq-ui/src/vethuq_ui/assets/icons/default.png
```

(`.jpeg` files reuse `jpg.png` — no separate file needed.)

Before moving on to wiring: `Read` each newly generated PNG (as an image,
not just checking the script printed `wrote ...`) and confirm it actually
looks like the intended icon. Generating one extra copy at a larger size
(e.g. 64px, via a second manifest entry) makes shape problems easier to
spot than squinting at 16px. This is the real defense against a mangled
SVG source (see the `WebFetch` caveat above) - a script that exits 0 only
proves the renderer didn't crash, not that the geometry is right.

If `generate_icons.py` itself needs a change (a new manifest field, a
different recolor rule, etc.), edit that script rather than writing a
parallel one-off — keep it as the single reusable implementation.

## Wiring the app to use them

In `packages/vethuq-ui/src/vethuq_ui/icons.py`, both icon kinds should load
the same way — `tk.PhotoImage(file=...)` (Tk 8.6+ decodes PNG natively, so
this needs no Pillow import in the app itself), cached in a module-level
dict so repeated calls don't reload from disk, resolved relative to
`Path(__file__).parent / "assets" / "icons"` rather than the process's
current working directory:

- Rewrite `get_file_icon(file_path)` to map a file's suffix to one of the
  file-type asset filenames (falling back to `default.png` for anything
  unrecognized) instead of extracting a Shell icon.
- Add `get_icon(name: str)` alongside it, keyed by logical name
  (`"search"`, `"sources"`, `"gpu"`, ...) rather than by file suffix, for
  the ribbon action icons.

Then, in `_build_menubar` (`app.py`), replace each button's Unicode-glyph
text (e.g. `text="\N{LEFT-POINTING MAGNIFYING GLASS}\nSearch"`) with a real
image: `ttk.Button(..., image=get_icon("search"), text="Search",
compound=tk.TOP)` — `compound=tk.TOP` reproduces the current
icon-above/caption-below ribbon look with an actual icon instead of an
emoji character. Keep a reference to each `PhotoImage` alive for the
button's lifetime (the module-level cache in `icons.py` already does this
across the whole app, so no extra bookkeeping is needed in `app.py`).

Finally remove the now-unused Windows Shell icon-extraction code and the
`pywin32` dependency:

- Delete the `win32*`/`PIL.ImageTk` extraction path in `icons.py`.
- Remove `pywin32; sys_platform == 'win32'` from
  `packages/vethuq-ui/pyproject.toml`.
- Remove the `win32api`/`win32con`/`win32gui`/`win32ui` mypy override in the
  root `pyproject.toml` (added specifically for that code).
- Run `uv sync --all-packages` from the repo root afterwards (this is a
  single-venv uv workspace — syncing just one package's deps has previously
  dropped other packages' dependencies from the shared venv, so always sync
  the whole workspace here).

## Verify

- `uv run ruff check packages/vethuq-ui` and
  `uv run mypy packages` (run from the repo root, matching
  `.pre-commit-config.yaml`'s `uv run mypy packages`).
- Launch the app (`uv run --package vethuq-ui vethuq-ui`) and check both:
  a search against a real or temporary indexed DB, to see the new file-type
  icons in the results list; and the Home/Settings ribbon tabs, to see the
  new action icons on the Search/Sources/GPU buttons.
