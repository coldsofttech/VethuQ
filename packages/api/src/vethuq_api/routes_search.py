"""The endpoints for search."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq_api.core import Core
from vethuq_api.routes_credits import _attachment


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def register(api: Blueprint, core: Core) -> None:
    @api.get("/search/options")
    def search_options() -> Response:
        return jsonify(core.search().options())

    @api.get("/files/text")
    def text_window() -> Response:
        """A window of lines of a text or Markdown file as it was indexed, for the preview."""
        try:
            return jsonify(core.search().text_window(request.args))
        except LookupError as error:
            return jsonify(error=str(error)), 404

    @api.get("/files/csv")
    def csv_window() -> Response:
        """A window of rows of a CSV file of a source, read from disk, for the table preview."""
        path = request.args.get("path")
        if (
            not isinstance(path, str)
            or not core.search().is_csv(path)
            or not core.sources().may_open(path)
        ):
            raise ValueError("Only a CSV file of a source that VethuQ reads can be shown here.")
        return jsonify(core.search().csv_window(path, request.args))

    # A search is read-only; it is a POST only because a query can be long and has many parts.
    @api.post("/search/run")
    def search_run() -> Response:
        return jsonify(core.search().run(_body()))

    @api.post("/search/export")
    def search_export() -> Response:
        body = _body()
        fmt = body.get("format")
        if fmt is not None and not isinstance(fmt, str):
            raise ValueError("format is json or html.")
        return _attachment(*core.search().export(body, fmt))
