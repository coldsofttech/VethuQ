"""The endpoints for the database check, updates, the policy, the search index and the tiers."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq_api.core import Core


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _flag(name: str) -> bool:
    value = _body().get(name)
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{name} is true or false.")
    return bool(value)


def register(api: Blueprint, core: Core) -> None:
    def service():  # noqa: ANN202
        return core.maintenance()

    @api.get("/maintenance/tasks")
    def tasks() -> Response:
        return jsonify(service().tasks())

    @api.get("/db")
    def db_status() -> Response:
        return jsonify(service().db_status())

    @api.post("/db/check")
    def db_check() -> tuple[Response, int]:
        return jsonify(service().db_check(_flag("quick"))), 202

    @api.get("/updates")
    def updates() -> Response:
        return jsonify(service().updates())

    @api.post("/updates/check")
    def updates_check() -> Response:
        return jsonify(service().updates_check(_flag("force")))

    @api.get("/policy")
    def policy() -> Response:
        return jsonify(service().policy())

    @api.post("/policy/refresh")
    def policy_refresh() -> Response:
        return jsonify(service().policy_refresh(_flag("force")))

    @api.get("/search-index")
    def search_index() -> Response:
        return jsonify(service().search_index())

    @api.post("/search-index/rebuild")
    def search_rebuild() -> tuple[Response, int]:
        return jsonify(service().search_rebuild()), 202

    @api.get("/metrics")
    def metrics() -> Response:
        return jsonify(service().metrics())

    @api.get("/metrics/preview")
    def metrics_preview() -> Response:
        return jsonify(service().metrics_preview())

    @api.post("/metrics/send")
    def metrics_send() -> Response:
        return jsonify(service().metrics_send(_flag("force")))

    @api.post("/metrics/delete-data")
    def metrics_delete() -> Response:
        return jsonify(service().metrics_delete())

    @api.get("/tiers")
    def tiers() -> Response:
        return jsonify(tiers=service().tiers())

    @api.post("/tiers/use")
    def tiers_use() -> Response:
        tier = _body().get("tier")
        if not isinstance(tier, str) or not tier.strip():
            raise ValueError("Say which tier.")
        return jsonify(service().tiers_use(tier))

    @api.post("/tiers/reset")
    def tiers_reset() -> Response:
        return jsonify(service().tiers_reset())
