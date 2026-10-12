# ui_temp: temporary UI checks

Throwaway scripts that let the UI be looked at from CI before it can be tried on a real machine.
Delete this folder and `.github/workflows/ui-temp.yml` when they are no longer needed. Nothing else
depends on them.

| Script | What it does | Output (`--out DIR`) |
|---|---|---|
| `browser_screens.py` | Starts `vethuq-desktop --no-window`, opens it in Chromium/Edge (the WebView2 engine) in light and dark, walks the pages, checks the title-bar buttons and that the start-up link works once | `browser-*.png` |
| `desktop_smoke.py` | Opens the **real** pywebview/WebView2 window, waits for the interface, checks the host, maximises, restores, switches to dark, and captures the screen | `desktop-*.png`, `desktop-result.json` |

Run them locally:

    cd web && npm ci && npm run build && cd ..
    uv run --with playwright python scripts/ui_temp/browser_screens.py --out shots   # any OS
    uv run python scripts/ui_temp/desktop_smoke.py --out shots                        # Windows
