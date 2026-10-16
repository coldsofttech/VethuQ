"""The endpoints for add-ons."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq_api.core import Core


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def register(api: Blueprint, core: Core) -> None:
    @api.get("/addons")
    def addons_list() -> Response:
        service = core.addons()
        return jsonify(
            installed=service.installed(),
            bundles=service.bundles(),
            install=service.can_install(),
        )

    def _language() -> str | None:
        language = request.args.get("language")
        return language[:16] if language else None

    @api.get("/addons/catalog")
    def addons_catalog() -> Response:
        return jsonify(core.addons().catalog(_language()))

    @api.post("/addons/catalog/refresh")
    def addons_catalog_refresh() -> Response:
        force = _body().get("force")
        if force is not None and not isinstance(force, bool):
            raise ValueError("force is true or false.")
        return jsonify(core.addons().catalog_refresh(bool(force), _language()))

    @api.get("/addons/job")
    def addons_job() -> Response:
        return jsonify(core.addons().job())

    @api.post("/addons/<addon_id>/enabled")
    def addons_enabled(addon_id: str) -> Response:
        enabled = _body().get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("enabled is true or false.")
        return jsonify(core.addons().set_enabled(addon_id, enabled))

    @api.post("/addons/<addon_id>/update")
    def addons_update(addon_id: str) -> tuple[Response, int]:
        return jsonify(core.addons().update(addon_id)), 202

    @api.post("/addons/bundles/<bundle>/install")
    def addons_install(bundle: str) -> tuple[Response, int]:
        return jsonify(core.addons().install(bundle)), 202
