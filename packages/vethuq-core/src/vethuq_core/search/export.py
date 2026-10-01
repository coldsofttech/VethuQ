"""Export `search` results to a JSON or HTML file."""

from __future__ import annotations

import functools
import html
import json
import locale
from datetime import datetime
from importlib import resources
from pathlib import Path

from vethuq_core.branding import APP_NAME, APP_TAGLINE
from vethuq_core.search.search import SearchMatch
from vethuq_core.settings import SearchSettings


class Export:
    _TEMPLATES = resources.files("vethuq_core.search") / "templates"

    @staticmethod
    @functools.cache
    def template(name: str) -> str:
        """The text of one of the export's template files (`templates/<name>`)."""
        return (Export._TEMPLATES / name).read_text(encoding="utf-8")

    @staticmethod
    def _matched_text(match: SearchMatch) -> str:
        prefix = "..." if match.truncated_before else ""
        suffix = "..." if match.truncated_after else ""
        return f"{prefix}{match.before}{match.matched}{match.after}{suffix}"

    @staticmethod
    def _file_uri(file_path: str) -> str:
        return Path(file_path).resolve().as_uri()

    @staticmethod
    def _generated_at() -> str:
        """The current local time, formatted per the user's locale (no ISO 'T' separator)."""
        try:
            locale.setlocale(locale.LC_TIME, "")
        except locale.Error:
            pass
        return datetime.now().astimezone().strftime("%c %Z").strip()

    @staticmethod
    def search_results(matches: list[SearchMatch], query: str, output: Path, format_: str) -> None:
        """Write `matches` for `query` to `output` as `format_` ('json' or 'html')."""
        if format_ not in SearchSettings.EXPORT_FORMATS:
            raise ValueError(f"format_ must be one of {SearchSettings.EXPORT_FORMATS}")
        if format_ == "json":
            Export._write_json(matches, query, output)
        else:
            Export._write_html(matches, query, output)

    @staticmethod
    def _write_json(matches: list[SearchMatch], query: str, output: Path) -> None:
        payload = {
            "query": query,
            "generated_at": Export._generated_at(),
            "result_count": len(matches),
            "matches": [
                {
                    "file_name": match.file_name,
                    "file_path": match.file_path,
                    "page_number": match.page_number,
                    "total_pages": match.total_pages,
                    "matched_text": Export._matched_text(match),
                }
                for match in matches
            ],
        }
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _write_html(matches: list[SearchMatch], query: str, output: Path) -> None:
        rows = []
        for match in matches:
            page = str(match.page_number) if match.page_number is not None else "-"
            total_pages = str(match.total_pages) if match.total_pages is not None else "-"
            snippet = html.escape(Export._matched_text(match)).replace(
                html.escape(match.matched), f"<mark>{html.escape(match.matched)}</mark>", 1
            )
            row = (
                Export.template("export_row.html")
                .replace("{{FILE_URI}}", html.escape(Export._file_uri(match.file_path)))
                .replace("{{FILE_NAME}}", html.escape(match.file_name))
                .replace("{{FILE_PATH}}", html.escape(match.file_path))
                .replace("{{PAGE}}", page)
                .replace("{{TOTAL_PAGES}}", total_pages)
                .replace("{{SNIPPET}}", snippet)
            )
            rows.append(row)

        document = (
            Export.template("export.html")
            .replace("{{STYLE}}", Export.template("export.css").rstrip("\n"))
            .replace("{{APP_NAME}}", html.escape(APP_NAME))
            .replace("{{APP_TAGLINE}}", html.escape(APP_TAGLINE))
            .replace("{{QUERY}}", html.escape(query))
            .replace("{{RESULT_COUNT}}", str(len(matches)))
            .replace("{{GENERATED_AT}}", html.escape(Export._generated_at()))
            .replace("{{ROWS}}", "\n".join(rows))
        )
        output.write_text(document, encoding="utf-8")
