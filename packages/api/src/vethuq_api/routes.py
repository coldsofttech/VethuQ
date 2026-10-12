"""The JSON endpoints."""

from __future__ import annotations

from collections.abc import Callable

from flask import Blueprint, Flask, Response, jsonify

from vethuq_api.window import WindowController


def _state(window: WindowController) -> Response:
    return jsonify(maximized=window.maximized)


def register(
    app: Flask,
    *,
    about: Callable[[], dict[str, object]],
    host_kind: str,
    window: WindowController | None,
) -> None:
    api = Blueprint("api", __name__, url_prefix="/api")

    @api.get("/health")
    def health() -> Response:
        return jsonify(status="ok")

    @api.get("/about")
    def get_about() -> Response:
        return jsonify(about())

    @api.get("/platform")
    def platform() -> Response:
        return jsonify(kind=host_kind, window_controls=window is not None)

    if window is not None:

        @api.get("/window/state")
        def window_state() -> Response:
            return _state(window)

        @api.post("/window/minimize")
        def window_minimize() -> Response:
            window.minimize()
            return _state(window)

        @api.post("/window/maximize")
        def window_maximize() -> Response:
            window.maximize()
            return _state(window)

        @api.post("/window/restore")
        def window_restore() -> Response:
            window.restore()
            return _state(window)

        @api.post("/window/close")
        def window_close() -> Response:
            window.close()
            return _state(window)

    app.register_blueprint(api)
