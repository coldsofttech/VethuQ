"""The endpoints for the GitHub tier."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq_addon_api import AddonError
from vethuq_api.core import Core
from vethuq_api.routes_credits import _int


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _text(body: dict[str, Any], name: str) -> str | None:
    value = body.get(name)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} is text.")
    return value.strip()


def _flag(body: dict[str, Any], name: str, default: bool = False) -> bool:
    value = body.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} is true or false.")
    return value


def register(api: Blueprint, core: Core) -> None:
    @api.errorhandler(AddonError)
    def _addon_error(error: AddonError) -> tuple[Response, int]:
        name = type(error).__name__
        status = 401 if name == "GitHubAuthError" else 409 if name == "GitHubNotSetUpError" else 422
        return jsonify(error=str(error), kind=name), status

    def service():  # noqa: ANN202
        return core.github()

    @api.get("/github")
    def github_overview() -> Response:
        return jsonify(service().overview())

    @api.get("/github/availability")
    def github_availability() -> Response:
        return jsonify(service().availability())

    @api.post("/github/status")
    def github_status() -> Response:
        return jsonify(service().status(_text(_body(), "token")))

    @api.post("/github/setup")
    def github_setup() -> tuple[Response, int]:
        body = _body()
        runner = service().setup(
            repo=_text(body, "repo") or "vethuq-runner",
            owner=_text(body, "owner"),
            private=_flag(body, "private", True),
            token=_text(body, "token"),
            master_key=_text(body, "master_key"),
            workflow_ref=_text(body, "workflow_ref"),
            create=_flag(body, "create", True),
            adopt=_flag(body, "adopt"),
        )
        if body.get("remember") is True:
            service().remember_token(_text(body, "token"))
        return jsonify(runner), 201

    @api.post("/github/update")
    def github_update() -> Response:
        body = _body()
        return jsonify(service().update(_text(body, "token"), _text(body, "workflow_ref")))

    @api.post("/github/remove")
    def github_remove() -> Response:
        body = _body()
        return jsonify(
            service().remove(
                _text(body, "token"),
                _flag(body, "delete_repo"),
                _flag(body, "delete_key"),
            )
        )

    @api.post("/github/token")
    def github_token() -> Response:
        return jsonify(service().remember_token(_text(_body(), "token")))

    @api.get("/github/jobs")
    def github_jobs() -> Response:
        return jsonify(jobs=service().jobs(min(_int("limit", 100), 500)))
