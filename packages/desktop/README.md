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

## Updates

When a newer VethuQ is available a dialog offers three choices:

- **Install now** downloads the installer named by the signed policy, checks that its size and sha256 match the policy entry (and that the address is https), stops the background service, runs the installer silently, starts the service again if it was running (Windows asks for permission, as it did to stop it), so queued indexing jobs carry on, and then opens VethuQ again (a silent install does not do that by itself). Nothing is run if the check fails, and the dialog says why.
- **Later** hides the notice for a day.
- **Skip this version** stops announcing that version; a newer one is announced again.

A version below the oldest supported one is explained but cannot be put off; indexing, search and your data keep working, and only features that need a newer version are held back. Installs that are not the installer (pip, pipx) show the upgrade command instead of Install now. Active notices from the policy are listed under Settings › Policy.

Settings › General › Updates chooses `on` (check and offer), `notify-only` (check and only tell me) or `off`. The environment variable `VETHUQ_UPDATE_CHECK=off` turns the check off whatever the setting says.

Checking for updates fetches one small signed file (the policy) from a static web host. The host sees your IP address and the request's fixed identity, `VethuQ-policy/1`. **Your VethuQ version is not sent**: the comparison happens on your computer. No telemetry is added, and GitHub Pages gives no access logs to us.

## Discover add-ons

Add-ons › **Discover** shows every add-on and bundle that exists, not only the ones installed here: a card for each with its description, whether it is free or licensed, the bundles it belongs to, and where it stands on this computer (installed, turned off, not installed, coming soon, no longer offered). For one that is not installed, **Ask for it** opens the address the catalog gives, or says to ask your administrator when it gives none. Search the list, or show only what is not installed. It reads the saved catalog; **Check now** looks for a newer one (and says why it could not, for instance when the update check is off). The fetch exposes your IP address, like the policy fetch, and nothing else. Add-ons › **Get more** installs the bundles VethuQ names with pip; Discover is for finding out what exists and asking for it.

## Known limits

- Windows only. The window is created with `gui="edgechromium"` and never falls back to the old
  Internet Explorer engine; Windows 11 ships the WebView2 runtime.
- The frameless window draws its own caption buttons. Native snap layouts on the maximize button and
  the exact resize edges depend on the platform and are to be checked on a real machine.
