"""The JSON endpoints."""

from __future__ import annotations

from flask import Blueprint, Flask, Response, jsonify, request

from vethuq_api import (
    routes_addons,
    routes_credits,
    routes_github,
    routes_logs,
    routes_maintenance,
    routes_ocr,
    routes_sources,
    routes_stats,
)
from vethuq_api.core import Core
from vethuq_api.settings import InvalidSettingError, SettingNotFoundError
from vethuq_api.window import WindowController


def _state(window: WindowController) -> Response:
    return jsonify(maximized=window.maximized)


def register(
    app: Flask,
    *,
    core: Core,
    host_kind: str,
    window: WindowController | None,
) -> None:
    api = Blueprint("api", __name__, url_prefix="/api")
    routes_sources.register(api, core, window)
    routes_credits.register(api, core)
    routes_stats.register(api, core)
    routes_ocr.register(api, core)
    routes_addons.register(api, core)
    routes_logs.register(api, core)
    routes_maintenance.register(api, core)
    routes_github.register(api, core)

    @api.get("/health")
    def health() -> Response:
        return jsonify(status="ok")

    @api.get("/about")
    def get_about() -> Response:
        return jsonify(core.about())

    @api.get("/brand")
    def brand() -> Response:
        return jsonify(core.brand())

    @api.get("/support-info")
    def support_info() -> Response:
        return Response(core.support_report(), mimetype="text/plain; charset=utf-8")

    @api.get("/catalog")
    def catalog() -> Response:
        return jsonify(core.catalog())

    @api.errorhandler(SettingNotFoundError)
    def _setting_not_found(error: SettingNotFoundError) -> tuple[Response, int]:
        return jsonify(error=str(error)), 404

    @api.errorhandler(InvalidSettingError)
    def _invalid_setting(error: InvalidSettingError) -> tuple[Response, int]:
        return jsonify(error=str(error)), 422

    @api.get("/settings/<section>")
    def list_settings(section: str) -> Response:
        return jsonify(section=section, settings=core.settings(section))

    @api.put("/settings/<section>/<setting_id>")
    def update_setting(section: str, setting_id: str) -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "value" not in body:
            raise InvalidSettingError('Send {"value": ...}.')
        options = body.get("options")
        if options is not None and not isinstance(options, dict):
            raise InvalidSettingError("Options are an object.")
        return jsonify(core.update_setting(section, setting_id, body["value"], options))

    @api.delete("/settings/<section>/<setting_id>")
    def reset_setting(section: str, setting_id: str) -> Response:
        body = request.get_json(silent=True)
        options = body.get("options") if isinstance(body, dict) else None
        return jsonify(core.reset_setting(section, setting_id, options))

    @api.get("/platform")
    def platform() -> Response:
        return jsonify(
            kind=host_kind,
            window_controls=window is not None,
            folder_dialog=callable(getattr(window, "choose_folder", None)),
            file_dialog=callable(getattr(window, "choose_file", None)),
            reveal=callable(getattr(window, "reveal", None)),
        )

    if window is not None and callable(getattr(window, "choose_folder", None)):

        @api.post("/dialog/folder")
        def choose_folder() -> Response:
            body = request.get_json(silent=True)
            start = body.get("start") if isinstance(body, dict) else None
            chosen = window.choose_folder(start if isinstance(start, str) else None)  # type: ignore[union-attr]
            return jsonify(path=chosen)

    if window is not None and callable(getattr(window, "choose_file", None)):

        @api.post("/dialog/file")
        def choose_file() -> Response:
            body = request.get_json(silent=True)
            start = body.get("start") if isinstance(body, dict) else None
            chosen = window.choose_file(start if isinstance(start, str) else None)  # type: ignore[union-attr]
            return jsonify(path=chosen)

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
            """Close the window, unless this application is running an index of its own: that
            stops with it, so the interface asks first and calls again with `force`."""
            body = request.get_json(silent=True)
            force = isinstance(body, dict) and body.get("force") is True
            indexing = core.indexing()
            if not force and indexing.one_off_active():
                return jsonify(maximized=window.maximized, closing=False, blocked="indexing")
            if force:
                indexing.stop_for_close()
            window.close()
            return jsonify(maximized=window.maximized, closing=True, blocked=None)

    app.register_blueprint(api)
