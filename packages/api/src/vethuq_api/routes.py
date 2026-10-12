"""The JSON endpoints."""

from __future__ import annotations

from flask import Blueprint, Flask, Response, jsonify, request

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

    @api.get("/health")
    def health() -> Response:
        return jsonify(status="ok")

    @api.get("/about")
    def get_about() -> Response:
        return jsonify(core.about())

    @api.get("/brand")
    def brand() -> Response:
        return jsonify(core.brand())

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
        return jsonify(core.update_setting(section, setting_id, body["value"]))

    @api.delete("/settings/<section>/<setting_id>")
    def reset_setting(section: str, setting_id: str) -> Response:
        return jsonify(core.reset_setting(section, setting_id))

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
