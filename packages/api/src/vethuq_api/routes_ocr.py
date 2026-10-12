"""The endpoints for OCR engines, phases and models."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq_api.core import Core


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _list(value: object, name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{name} is a list of words.")
    return value


def register(api: Blueprint, core: Core) -> None:
    @api.get("/ocr")
    def ocr_overview() -> Response:
        service = core.ocr()
        return jsonify(engines=service.engines(), phases=service.phases())

    @api.get("/ocr/models")
    def ocr_models() -> Response:
        return jsonify(core.ocr().models(request.args.getlist("language") or None))

    @api.get("/ocr/job")
    def ocr_job() -> Response:
        return jsonify(core.ocr().job())

    @api.post("/ocr/models/<action>")
    def ocr_models_start(action: str) -> tuple[Response, int]:
        body = _body()
        job = core.ocr().start(
            action, _list(body.get("languages"), "languages"), _list(body.get("names"), "names")
        )
        return jsonify(job), 202

    @api.post("/ocr/models/clear")
    def ocr_models_clear() -> Response:
        body = _body()
        languages = _list(body.get("languages"), "languages") or []
        removed = core.ocr().clear(languages, body.get("include_shared") is True)
        return jsonify(removed=removed)

    @api.post("/ocr/models/clean")
    def ocr_models_clean() -> Response:
        return jsonify(removed=core.ocr().clean())
