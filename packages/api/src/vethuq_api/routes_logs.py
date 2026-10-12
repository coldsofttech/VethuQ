"""The endpoints for logs."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from vethuq_api.core import Core
from vethuq_api.routes_credits import _attachment, _int, _opt


def register(api: Blueprint, core: Core) -> None:
    @api.get("/logs")
    def logs_components() -> Response:
        return jsonify(components=core.logs().components())

    def _filters() -> dict[str, object]:
        return {
            "day": _opt("day"),
            "level": _opt("level"),
            "contains": request.args.get("contains") or None,
            "order": request.args.get("order", "asc"),
        }

    @api.get("/logs/<component>")
    def logs_entries(component: str) -> Response:
        after = request.args.get("after")
        data = core.logs().entries(
            component,
            limit=_int("limit", 500),
            after=_int("after", 0) if after not in (None, "") else None,
            **_filters(),  # type: ignore[arg-type]
        )
        return jsonify(data)

    @api.get("/logs/<component>/export")
    def logs_export(component: str) -> Response:
        data, name = core.logs().export(component, **_filters())  # type: ignore[arg-type]
        return _attachment(data, name, "text/plain")
