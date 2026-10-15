"""The endpoints for search."""

from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, Response, jsonify, request, send_file

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

    @api.get("/files/markdown")
    def markdown_file() -> Response:
        """A Markdown file of a source as it is on disk, for the rendered preview."""
        path = request.args.get("path")
        if (
            not isinstance(path, str)
            or not core.search().is_markdown(path)
            or not core.sources().may_open(path)
        ):
            raise ValueError(
                "Only a Markdown file of a source that VethuQ reads can be shown here."
            )
        return jsonify(core.search().source_file(path))

    # The preview of a file the index keeps in another shape (a stylesheet re-flowed, a web page
    # without its tags, JSON and YAML and XML flattened to `path: value` lines, a script without its
    # blank lines): the file as it is on disk, one route for each type.
    def source_route(file_type: str, what: str) -> None:
        def view() -> Response:
            path = request.args.get("path")
            if (
                not isinstance(path, str)
                or not core.search().is_type(path, file_type)
                or not core.sources().may_open(path)
            ):
                raise ValueError(f"Only {what} of a source that VethuQ reads can be shown here.")
            return jsonify(core.search().source_file(path))

        api.add_url_rule(f"/files/{file_type}", endpoint=f"{file_type}_file", view_func=view)

    for kind, what in (
        ("css", "a stylesheet"),
        ("html", "a web page"),
        ("json", "a JSON file"),
        ("yaml", "a YAML file"),
        ("ndjson", "an NDJSON file"),
        ("js", "a script"),
        ("xml", "an XML file"),
    ):
        source_route(kind, what)

    # Pictures: JPEG and PNG as they are (a browser draws them), a TIFF one frame at a time as PNG,
    # a GIF, WebP or HEIC one page at a time as PNG, and a BMP as PNG (a run-length encoded, OS/2
    # or headerless one is not drawn by every browser).
    def picture_route(file_type: str, what: str) -> None:
        def view() -> Response:
            path = request.args.get("path")
            if (
                not isinstance(path, str)
                or not core.search().is_type(path, file_type)
                or not core.sources().may_open(path)
            ):
                raise ValueError(f"Only {what} of a source that VethuQ reads can be shown here.")
            if file_type == "tiff":
                response = Response(
                    core.search().tiff_frame(path, request.args), mimetype="image/png"
                )
            elif file_type == "gif":
                response = Response(
                    core.search().gif_page(path, request.args), mimetype="image/png"
                )
            elif file_type == "webp":
                response = Response(
                    core.search().webp_page(path, request.args), mimetype="image/png"
                )
            elif file_type == "heic":
                response = Response(
                    core.search().heic_page(path, request.args), mimetype="image/png"
                )
            elif file_type == "bmp":
                response = Response(core.search().bmp_image(path), mimetype="image/png")
            else:
                response = send_file(
                    os.path.realpath(path),
                    mimetype="image/jpeg" if file_type == "jpg" else "image/png",
                    conditional=True,
                    max_age=0,
                )
            response.headers["Content-Disposition"] = "inline"
            return response

        api.add_url_rule(f"/files/{file_type}", endpoint=f"{file_type}_file", view_func=view)

    for kind, what in (
        ("jpg", "a JPEG picture"),
        ("png", "a PNG picture"),
        ("tiff", "a TIFF picture"),
        ("bmp", "a BMP picture"),
        ("gif", "a GIF picture"),
        ("webp", "a WebP picture"),
        ("heic", "a HEIC picture"),
    ):
        picture_route(kind, what)

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

    @api.get("/files/mhtml")
    def mhtml_page() -> Response:
        """A web archive of a source, made into one page for the rendered preview."""
        path = request.args.get("path")
        if (
            not isinstance(path, str)
            or not core.search().is_mhtml(path)
            or not core.sources().may_open(path)
        ):
            raise ValueError("Only an MHTML file of a source that VethuQ reads can be shown here.")
        return jsonify(core.search().mhtml_page(path))

    @api.get("/files/tsv")
    def tsv_window() -> Response:
        """A window of rows of a TSV file of a source: the same table preview as for CSV."""
        path = request.args.get("path")
        if (
            not isinstance(path, str)
            or not core.search().is_tsv(path)
            or not core.sources().may_open(path)
        ):
            raise ValueError("Only a TSV file of a source that VethuQ reads can be shown here.")
        return jsonify(core.search().tsv_window(path, request.args))

    @api.get("/files/parquet")
    def parquet_window() -> Response:
        """A window of rows of a Parquet table of a source, for the same table preview."""
        path = request.args.get("path")
        if (
            not isinstance(path, str)
            or not core.search().is_parquet(path)
            or not core.sources().may_open(path)
        ):
            raise ValueError("Only a Parquet file of a source that VethuQ reads can be shown here.")
        return jsonify(core.search().parquet_window(path, request.args))

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
