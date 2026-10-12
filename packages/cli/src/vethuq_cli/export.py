"""`--export` and `--format` for the listing commands: write the list to a JSON or HTML file.

    @source_app.command("list")
    @exportable("Sources", "sources", facets=("source_type", "status"))
    def source_list(...): ...

The decorator adds the two options to the command. While the command runs, `table()` sees the
request and writes the file, through `client.export.records`, instead of printing.
"""

from __future__ import annotations

import functools
import html
import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from vethuq_cli.console import Theme
from vethuq_cli.output import cell, plain, say
from vethuq_cli.state import State

HEADERS = {"id": "ID", "uri": "URI", "sha256": "SHA-256"}


@dataclass(frozen=True)
class ExportRequest:
    """What `--export` asked for, and how the listing is shown in HTML."""

    output: Path
    format: str | None
    title: str
    key: str
    facets: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ("status",)
    paths: tuple[str, ...] = ("path", "file_path")


class ListExport:
    """Writing a listing's rows to the file `--export` named."""

    @staticmethod
    def header(column: str, headers: Mapping[str, str] | None) -> str:
        if headers and column in headers:
            return headers[column]
        return HEADERS.get(column) or column.replace("_", " ").title()

    @staticmethod
    def formats(
        records: list[dict[str, Any]], columns: Sequence[str]
    ) -> dict[str, Callable[[object], str]]:
        """Cells that are not plain text (yes/no, numbers, lists) show as the table shows them."""
        shown = {}
        for column in columns:
            values = [r.get(column) for r in records if r.get(column) is not None]
            if any(not isinstance(v, str | int) or isinstance(v, bool) for v in values):
                shown[column] = lambda value: html.escape(cell(value))
        return shown

    @classmethod
    def write(
        cls,
        request: ExportRequest,
        rows: Sequence[Any],
        columns: Sequence[str],
        headers: Mapping[str, str] | None = None,
    ) -> Path:
        records = [plain(row) for row in rows]
        facets = tuple(f for f in request.facets if f in columns)
        path = State.client().export.records(
            records,
            [(c, cls.header(c, headers)) for c in columns],
            request.output,
            request.format,
            title=request.title,
            key=request.key,
            statuses=tuple(c for c in request.statuses if c in columns),
            paths=tuple(c for c in request.paths if c in columns),
            facets=facets,
            formats=cls.formats(records, columns),
        )
        say(
            f"Wrote {len(records)} {request.title.lower()} to {path}.",
            style=Theme.OK,
            data={"path": str(path)},
        )
        return path


def exportable(
    title: str,
    key: str,
    *,
    facets: tuple[str, ...] = (),
    statuses: tuple[str, ...] = ("status",),
    paths: tuple[str, ...] = ("path", "file_path"),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Give a listing command `--export FILE` and `--format json|html`."""

    def decorate(command: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(command)
        def wrapper(*args: Any, export: Path | None = None, export_format: str | None = None, **kw):
            if export_format and not export:
                raise typer.BadParameter("--format needs --export.", param_hint="--format")
            State.export = (
                ExportRequest(export, export_format, title, key, facets, statuses, paths)
                if export
                else None
            )
            try:
                return command(*args, **kw)
            finally:
                State.export = None

        signature = inspect.signature(command)
        options = [
            inspect.Parameter(
                "export",
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(
                    None, "--export", help="Write the list to this file instead of printing it."
                ),
                annotation=Path | None,
            ),
            inspect.Parameter(
                "export_format",
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(
                    None,
                    "--format",
                    help="json or html (with --export; default: the saved export format).",
                ),
                annotation=str | None,
            ),
        ]
        wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
            parameters=[*signature.parameters.values(), *options]
        )
        wrapper.__annotations__ = {
            **getattr(command, "__annotations__", {}),
            "export": Path | None,
            "export_format": str | None,
        }
        return wrapper

    return decorate
