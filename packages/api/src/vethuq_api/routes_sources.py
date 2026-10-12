"""The endpoints for sources and indexing."""

from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, Response, jsonify, request

from vethuq.errors import (
    CreditsError,
    FileNotTrackedError,
    IndexAlreadyRunningError,
    IndexJobNotFoundError,
    IndexJobStateError,
    IndexNotRunningError,
    IndexRunNotFoundError,
    SourceAlreadyExistsError,
    SourceNotFoundError,
    SourceNotRemovedError,
    SourceOverlapError,
    VethuQError,
)
from vethuq_api.core import Core
from vethuq_api.indexing import IndexingRefusedError

_NOT_FOUND = (
    SourceNotFoundError,
    IndexRunNotFoundError,
    FileNotTrackedError,
    IndexJobNotFoundError,
)
_CONFLICT = (
    SourceAlreadyExistsError,
    SourceOverlapError,
    SourceNotRemovedError,
    IndexAlreadyRunningError,
    IndexNotRunningError,
    IndexJobStateError,
)


def _int(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except ValueError as error:
        raise ValueError(f"{name} is a whole number.") from error


def _flag(name: str) -> bool:
    return request.args.get(name, "").lower() in ("1", "true", "yes")


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _target(value: object) -> int | str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | str):
        return value
    raise ValueError("target is a source id or a path.")


def _attachment(data: bytes, name: str, mime: str) -> Response:
    response = Response(data, mimetype=mime)
    response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def register(api: Blueprint, core: Core, window: Any) -> None:
    @api.errorhandler(VethuQError)
    def _core_error(error: VethuQError) -> tuple[Response, int]:
        if isinstance(error, _NOT_FOUND):
            code = 404
        elif isinstance(error, _CONFLICT):
            code = 409
        elif isinstance(error, CreditsError):
            code = 402
        else:
            code = 422
        return jsonify(error=str(error)), code

    @api.errorhandler(ValueError)
    def _bad_value(error: ValueError) -> tuple[Response, int]:
        return jsonify(error=str(error)), 422

    @api.errorhandler(IndexingRefusedError)
    def _refused(error: IndexingRefusedError) -> tuple[Response, int]:
        return jsonify(error=str(error)), error.status

    # ----- sources ----------------------------------------------------------------------------

    @api.get("/sources")
    def sources_list() -> Response:
        rows = core.sources().list(
            removed=_flag("removed"),
            status=request.args.get("status"),
            source_type=request.args.get("type"),
            language=request.args.get("language"),
            q=request.args.get("q", ""),
            sort=request.args.get("sort", "id"),
            order=request.args.get("order", "asc"),
        )
        return jsonify(sources=rows)

    @api.post("/sources")
    def sources_add() -> tuple[Response, int]:
        body = _body()
        path = body.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Give the path of a folder or a file.")
        languages = body.get("languages")
        if languages is not None and not isinstance(languages, list):
            raise ValueError("languages is a list of language ids.")
        return jsonify(core.sources().add(path.strip(), languages)), 201

    @api.get("/sources/export")
    def sources_export() -> Response:
        data, name, mime = core.sources().export_sources(
            request.args.get("format", "json"), _flag("removed")
        )
        return _attachment(data, name, mime)

    @api.get("/sources/<int:source_id>")
    def sources_get(source_id: int) -> Response:
        return jsonify(core.sources().get(source_id))

    @api.delete("/sources/<int:source_id>")
    def sources_remove(source_id: int) -> Response:
        return jsonify(core.sources().remove(source_id))

    @api.post("/sources/<int:source_id>/restore")
    def sources_restore(source_id: int) -> Response:
        return jsonify(core.sources().restore(source_id))

    @api.post("/sources/<int:source_id>/purge")
    def sources_purge(source_id: int) -> Response:
        return jsonify(core.sources().purge(source_id))

    @api.put("/sources/<int:source_id>/languages")
    def sources_languages(source_id: int) -> Response:
        languages = _body().get("languages")
        if languages is not None and not isinstance(languages, list):
            raise ValueError("languages is a list of language ids.")
        return jsonify(core.sources().set_languages(source_id, languages))

    def _file_filters() -> dict[str, Any]:
        minimum = request.args.get("min_confidence")
        return {
            "q": request.args.get("q", ""),
            "status": request.args.get("status") or None,
            "file_type": request.args.get("type") or None,
            "band": request.args.get("band") or None,
            "min_confidence": float(minimum) if minimum else None,
        }

    @api.get("/sources/<int:source_id>/files")
    def sources_files(source_id: int) -> Response:
        page = core.sources().files(
            source_id,
            **_file_filters(),
            sort=request.args.get("sort", "path"),
            order=request.args.get("order", "asc"),
            offset=_int("offset", 0),
            limit=min(_int("limit", 200), 1000),
            refresh=_flag("refresh"),
        )
        return jsonify(page)

    @api.get("/sources/<int:source_id>/files/export")
    def sources_files_export(source_id: int) -> Response:
        data, name, mime = core.sources().export_files(
            source_id, request.args.get("format", "json"), **_file_filters()
        )
        return _attachment(data, name, mime)

    # ----- indexing ---------------------------------------------------------------------------

    seen: dict[str, object] = {}

    @api.get("/index/state")
    def index_state() -> Response:
        state = core.indexing().state()
        run = state["run"] if isinstance(state["run"], dict) else {}
        progress = (
            run.get("id"),
            run.get("status"),
            run.get("files_processed"),
            run.get("files_failed"),
        )
        if seen.get("progress") != progress:
            seen["progress"] = progress
            core.sources().forget()  # the files of a source have new states
        return jsonify(state)

    @api.post("/index/refresh")
    def index_refresh() -> Response:
        core.sources().forget()
        return jsonify(core.indexing().refresh())

    @api.post("/index/start")
    def index_start() -> tuple[Response, int]:
        body = _body()
        mode = body.get("mode", "run")
        if not isinstance(mode, str):
            raise ValueError("mode is a word.")
        state = core.indexing().start(mode, _target(body.get("target")))
        core.sources().forget()
        return jsonify(state), 202

    @api.post("/index/pause")
    def index_pause() -> Response:
        return jsonify(core.indexing().pause())

    @api.post("/index/resume")
    def index_resume() -> Response:
        return jsonify(core.indexing().resume())

    @api.post("/index/stop")
    def index_stop() -> Response:
        return jsonify(core.indexing().stop())

    @api.get("/index/history")
    def index_history() -> Response:
        runs = core.indexing().history(
            status=request.args.get("status"),
            target=_target(request.args.get("target")),
            sort=request.args.get("sort", "started_at"),
            order=request.args.get("order", "desc"),
            offset=_int("offset", 0),
            limit=min(_int("limit", 50), 500),
        )
        return jsonify(runs=runs)

    @api.get("/index/jobs")
    def index_jobs() -> Response:
        return jsonify(jobs=core.indexing().jobs(min(_int("limit", 50), 500)))

    @api.get("/index/requests")
    def index_requests() -> Response:
        return jsonify(requests=core.indexing().requests(min(_int("limit", 50), 500)))

    @api.post("/index/requests/<int:job_id>/cancel")
    def index_cancel(job_id: int) -> Response:
        return jsonify(core.indexing().cancel_request(job_id))

    @api.post("/service/<action>")
    def service_action(action: str) -> Response:
        return jsonify(core.indexing().service_action(action))

    # ----- the host ---------------------------------------------------------------------------

    @api.post("/os/open")
    def open_file() -> Response:
        """Open a file of a source in its own application. Only a file VethuQ reads, inside one of
        the sources, can be opened this way: this is not a way to start any program."""
        path = _body().get("path")
        if window is None or not callable(getattr(window, "open_file", None)):
            return jsonify(error="This host cannot open a file in its application."), 404
        if not isinstance(path, str) or not core.sources().may_open(path):
            raise ValueError("Only a file of a source that VethuQ reads can be opened here.")
        window.open_file(path)
        return jsonify(ok=True)

    @api.post("/os/reveal")
    def reveal() -> Response:
        path = _body().get("path")
        if window is None or not callable(getattr(window, "reveal", None)):
            return jsonify(error="This host cannot show a file in its folder."), 404
        if not isinstance(path, str) or not os.path.exists(path):
            raise ValueError("That path is not on disk.")
        window.reveal(path)
        return jsonify(ok=True)
