# vethuq-api

The HTTP API behind the VethuQ user interface. It is a thin Flask layer over the public `vethuq`
package: routes validate input, call the core and return JSON. No business logic lives here.

The same application is meant to serve the desktop host (`vethuq-desktop`) and, later, a normal web
deployment.

## Security model

The application assumes it is reachable by other programs on the same machine, so every request is
checked:

| Check | What it stops |
|---|---|
| `Host` must be exactly `127.0.0.1:<port>` | DNS rebinding |
| `Origin` must be the app's own origin on `POST`/`PUT`/`PATCH`/`DELETE` | Cross-site requests from a web page |
| `/api/*` needs the session cookie (`HttpOnly`, `SameSite=Strict`) | Other local programs and web pages |
| The start-up token in the first URL works **once** and is then replaced by a random session id | Replaying a leaked launch URL |
| Strict `Content-Security-Policy`, `nosniff`, `no-referrer`, no CORS headers | Script injection and cross-origin reads |

`/api/health` is the only unauthenticated endpoint; it reveals nothing but `{"status": "ok"}`.

The CSP allows inline *styles* (Fluent UI injects style rules at run time) but no inline or remote
scripts.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Readiness probe |
| `GET /api/about` | What the installation runs (`VethuQ().version`) |
| `GET /api/brand` | App name, tagline and the colour palette (light and dark) shared with the CLI and exports |
| `GET /api/catalog` | What is installed: add-ons, file types, search engines, languages, OCR engines (what the CLI lists) |
| `GET /api/settings/<section>` | The settings of a section (`indexing`, `general`, `sources`, `tiers`, `results`, `system`), each with its type, value, default, allowed values and where it applies |
| `PUT /api/settings/<section>/<id>` `{"value": ...}` | Change one setting; `422` with the reason if the value is refused |
| `DELETE /api/settings/<section>/<id>` | Put its default back |
| `GET /api/platform` | `{kind, window_controls}`: what the host offers the interface |
| `GET /api/window/state`, `POST /api/window/{minimize,maximize,restore,close}` | Window controls (only when the host passes a window controller) |

## Using it

```python
from vethuq_api import create_app, allow_host

app = create_app(bootstrap_token="...", web_dist=Path("web/dist"))
allow_host(app, "127.0.0.1:8765")  # every host:port the server answers on
```
