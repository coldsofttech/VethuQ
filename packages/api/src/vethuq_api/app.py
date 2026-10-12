"""The Flask application factory."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    make_response,
    redirect,
    request,
    send_from_directory,
)
from werkzeug.exceptions import HTTPException

from vethuq_api import routes, security
from vethuq_api.window import WindowController

_HASHED_ASSETS = "public, max-age=31536000, immutable"


def _default_about() -> Callable[[], dict[str, object]]:
    """Describe the installation through the public `vethuq` API (created on first use)."""
    lock = threading.Lock()
    client = None

    def about() -> dict[str, object]:
        nonlocal client
        with lock:
            if client is None:
                from vethuq import VethuQ

                client = VethuQ()
        return client.version.to_dict()

    return about


def create_app(
    *,
    bootstrap_token: str,
    web_dist: Path | None = None,
    window: WindowController | None = None,
    host_kind: str = "web",
    about: Callable[[], dict[str, object]] | None = None,
) -> Flask:
    """Build the application.

    `bootstrap_token` is the one-time secret in the first URL the host opens. `web_dist` is the
    built React interface to serve. `window` is given by hosts that own a window. `about`
    replaces the installation details (for tests). Call `allow_host` for every `host:port` the
    server answers on.
    """
    app = Flask(__name__, static_folder=None)
    app.config["ALLOWED_HOSTS"] = set()
    app.json.sort_keys = False
    gate = security.SessionGate(bootstrap_token)
    security.install(app, gate)
    routes.register(app, about=about or _default_about(), host_kind=host_kind, window=window)

    @app.errorhandler(HTTPException)
    def _http_error(error: HTTPException) -> Response:
        if request.path.startswith("/api/"):
            response = jsonify(error=error.name)
            response.status_code = error.code or 500
            return response
        return error.get_response()

    dist = web_dist.resolve() if web_dist is not None else None

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def interface(path: str) -> Response:
        if path.startswith("api/"):
            abort(404)
        token = request.args.get(security.BOOTSTRAP_PARAM)
        if token is not None:
            return _sign_in(token)
        if dist is None or not (dist / "index.html").is_file():
            return make_response(jsonify(error="The interface has not been built"), 503)
        candidate = (dist / path).resolve() if path else None
        if candidate is not None and candidate.is_file() and candidate.is_relative_to(dist):
            response = send_from_directory(dist, candidate.relative_to(dist).as_posix())
            if path.startswith("assets/"):
                response.headers["Cache-Control"] = _HASHED_ASSETS
            return response
        if "." in path.rsplit("/", 1)[-1]:
            abort(404)
        response = send_from_directory(dist, "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response

    def _sign_in(token: str) -> Response:
        session_id = gate.redeem(token)
        if session_id is None:
            return make_response(jsonify(error="The start-up link is not valid"), 403)
        # Send the browser to the clean URL so the token never stays in the address or history.
        response = redirect("/", code=303)
        response.set_cookie(
            security.SESSION_COOKIE,
            session_id,
            httponly=True,
            samesite="Strict",
            path="/",
        )
        return response

    return app


def allow_host(app: Flask, host: str) -> None:
    """Accept requests whose Host header is `host` (e.g. `127.0.0.1:8765`)."""
    app.config["ALLOWED_HOSTS"].add(host)
