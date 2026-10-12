# vethuq-desktop

The VethuQ desktop application for Windows 11.

    React (web/)  ──HTTP──▶  Flask (vethuq-api, 127.0.0.1:<free port>)  ──▶  VethuQ core
          ▲
    pywebview window (Microsoft Edge WebView2, no frame; the interface draws its own title bar)

On start it

1. picks a free port on `127.0.0.1` and starts the API in a background thread,
2. opens a window on `http://127.0.0.1:<port>/?t=<one-time token>`; the API swaps the token for a
   session cookie and redirects to the clean URL,
3. stops the server when the window closes.

## Run it (development)

    cd web && npm ci && npm run build        # builds web/dist
    uv run vethuq-desktop                    # opens the window (Windows)
    uv run vethuq-desktop --no-window        # serves only; prints the URL to open in a browser

`npm run dev` (in `web/`) rebuilds on every change; reload the window or browser to see it. There is
no separate dev server, which keeps the security model (one origin, one cookie) identical to
production.

`--no-window` prints one JSON line, `{"url": "http://127.0.0.1:PORT/?t=TOKEN"}`, and keeps serving
until it is interrupted. In that mode the window controls are simulated so the title bar can be
exercised in a browser.

## Where the built interface is looked for

1. `--web-dist PATH` or `VETHUQ_WEB_DIST`
2. `vethuq_desktop/web/` inside the installed package (for the packaged application)
3. `web/dist` of a source checkout

## Folder picker

Settings that name a folder (the data and backups folders) start with the system folder picker: the
window controller shows it (`choose_folder`, through `POST /api/dialog/folder`), and the chosen folder
is then confirmed in the interface. A host without a picker (`--no-window`, a browser) types the
folder instead.

## Known limits

- Windows only. The window is created with `gui="edgechromium"` and never falls back to the old
  Internet Explorer engine; Windows 11 ships the WebView2 runtime.
- The frameless window draws its own caption buttons. Native snap layouts on the maximize button and
  the exact resize edges depend on the platform and are to be checked on a real machine.
