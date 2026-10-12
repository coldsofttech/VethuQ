"""The endpoints for statistics."""

from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq_api.core import Core
from vethuq_api.routes_credits import _attachment, _int


def _filters() -> dict[str, Any]:
    names = ("source", "language", "file_type", "engine", "page_source", "band", "since", "until")
    return {name: request.args.get(name) or None for name in names}


def register(api: Blueprint, core: Core) -> None:
    @api.get("/stats/summary")
    def stats_summary() -> Response:
        return jsonify(core.stats().summary(**_filters()))

    @api.get("/stats/breakdown")
    def stats_breakdown() -> Response:
        data = core.stats().breakdown(
            group_by=request.args.get("group_by", "source"),
            sort=request.args.get("sort", "key"),
            order=request.args.get("order", "asc"),
            offset=_int("offset", 0),
            limit=min(_int("limit", 100), 1000),
            **_filters(),
        )
        if request.args.get("group_by", "source") == "source":
            ids = core.stats().source_ids()
            for row in data["items"]:  # type: ignore[union-attr]
                row["source_id"] = ids.get(row["key"])
                row["name"] = os.path.basename(str(row["key"]).rstrip("\\/")) or row["key"]
        return jsonify(data)

    @api.get("/stats/export")
    def stats_export() -> Response:
        data = core.stats().breakdown(
            group_by=request.args.get("group_by", "source"),
            sort=request.args.get("sort", "key"),
            order=request.args.get("order", "asc"),
            offset=0,
            limit=100000,
            **_filters(),
        )
        return _attachment(*core.stats().export(data["items"], request.args.get("format", "csv")))  # type: ignore[arg-type]
