"""Export `search` results and `source list` output to a JSON or HTML file."""

from __future__ import annotations

import functools
import html
import json
import locale
from datetime import datetime
from importlib import resources
from pathlib import Path

from vethuq_core.branding import APP_NAME, APP_TAGLINE, Palette
from vethuq_core.formatting import Formatting
from vethuq_core.paths.fspath import FsPath
from vethuq_core.search.engines import Ranking
from vethuq_core.search.search import SearchMatch
from vethuq_core.settings import SearchSettings
from vethuq_core.sources import Source, SourceFile


class Export:
    _TEMPLATES = resources.files("vethuq_core.search") / "templates"

    @staticmethod
    @functools.cache
    def template(name: str) -> str:
        """The text of one of the export's template files (`templates/<name>`)."""
        return (Export._TEMPLATES / name).read_text(encoding="utf-8")

    @staticmethod
    def _match_type(match: SearchMatch) -> str:
        """How the match was found, as the CLI and UI name it (`Exact`, `Similar 83%`), or ''."""
        return Ranking.hit_badge(match) if match.engine in Ranking.BADGES else ""

    @staticmethod
    def _matched_text(match: SearchMatch) -> str:
        prefix = "..." if match.truncated_before else ""
        suffix = "..." if match.truncated_after else ""
        return f"{prefix}{match.before}{match.matched}{match.after}{suffix}"

    @staticmethod
    def _file_uri(file_path: str) -> str:
        return FsPath.plain(FsPath.extended(file_path).resolve()).as_uri()

    @staticmethod
    def _generated_at() -> str:
        """The current local time, formatted per the user's locale (no ISO 'T' separator)."""
        try:
            locale.setlocale(locale.LC_TIME, "")
        except locale.Error:
            pass
        return datetime.now().astimezone().strftime("%c %Z").strip()

    @staticmethod
    def search_results(
        matches: list[SearchMatch],
        query: str,
        output: Path,
        format_: str,
        *,
        engine: str | None = None,
        case_sensitive: bool = False,
        threshold: float | None = None,
        distance: int | None = None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> None:
        """Write `matches` for `query` to `output` as `format_` ('json' or 'html').

        `engine`, `case_sensitive`, and - for the fuzzy, proximity, like (look-alikes) and
        noise-fuzzy engines - the `threshold`, `distance`, `level` or `noise` record how the
        search was run, so the export can be reproduced; they're omitted from the file when
        `engine` is None, and `threshold`/`distance`/`level`/`noise` when they are. A `unicode`
        level other than `off` is recorded too.
        """
        if format_ not in SearchSettings.EXPORT_FORMATS:
            raise ValueError(f"format_ must be one of {SearchSettings.EXPORT_FORMATS}")
        if format_ == "json":
            Export._write_json(
                matches,
                query,
                output,
                engine,
                case_sensitive,
                threshold,
                distance,
                level,
                noise,
                unicode,
            )
        else:
            Export._write_html(
                matches,
                query,
                output,
                engine,
                case_sensitive,
                threshold,
                distance,
                level,
                noise,
                unicode,
            )

    @staticmethod
    def _match_entry(match: SearchMatch) -> dict[str, object]:
        entry: dict[str, object] = {
            "file_name": match.file_name,
            "file_path": match.file_path,
            "page_number": match.page_number,
            "total_pages": match.total_pages,
            "matched_text": Export._matched_text(match),
        }
        if match.engine is not None:
            entry["engine"] = match.engine
        if match.matched_by:
            entry["matched_by"] = list(match.matched_by)
        if match.modifiers:
            entry["modifiers"] = list(match.modifiers)
        if match.score is not None:
            entry["score"] = match.score
        return entry

    @staticmethod
    def _write_json(
        matches: list[SearchMatch],
        query: str,
        output: Path,
        engine: str | None,
        case_sensitive: bool,
        threshold: float | None,
        distance: int | None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> None:
        payload: dict[str, object] = {"query": query}
        if engine is not None:
            payload["engine"] = engine
            payload["case_sensitive"] = case_sensitive
            if threshold is not None:
                payload["threshold"] = threshold
            if distance is not None:
                payload["distance"] = distance
            if level is not None:
                payload["leet_level"] = level
            if noise is not None:
                payload["noise"] = noise
            if unicode is not None and unicode != "off":
                payload["unicode"] = unicode
        payload["generated_at"] = Export._generated_at()
        payload["result_count"] = len(matches)
        payload["matches"] = [Export._match_entry(match) for match in matches]
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _write_html(
        matches: list[SearchMatch],
        query: str,
        output: Path,
        engine: str | None,
        case_sensitive: bool,
        threshold: float | None,
        distance: int | None,
        level: str | None = None,
        noise: str | None = None,
        unicode: str | None = None,
    ) -> None:
        search_mode = ""
        if engine is not None:
            search_mode = f" &middot; engine: {html.escape(engine)}"
            if case_sensitive:
                search_mode += ", case-sensitive"
            if threshold is not None:
                search_mode += f", threshold {threshold:.0%}"
            if distance is not None:
                search_mode += f", within {distance} words"
            if level is not None:
                search_mode += f", leet level {html.escape(level)}"
            if noise is not None:
                search_mode += f", noise {html.escape(noise)}"
            if unicode is not None and unicode != "off":
                search_mode += f", unicode {html.escape(unicode)}"
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
                .replace("{{MATCH}}", html.escape(Export._match_type(match)))
                .replace("{{SNIPPET}}", snippet)
            )
            rows.append(row)

        document = (
            Export.template("export.html")
            .replace("{{PALETTE}}", Palette.css_variables())
            .replace("{{STYLE}}", Export.template("export.css").rstrip("\n"))
            .replace("{{APP_NAME}}", html.escape(APP_NAME))
            .replace("{{APP_TAGLINE}}", html.escape(APP_TAGLINE))
            .replace("{{QUERY}}", html.escape(query))
            .replace("{{RESULT_COUNT}}", str(len(matches)))
            .replace("{{SEARCH_MODE}}", search_mode)
            .replace("{{GENERATED_AT}}", html.escape(Export._generated_at()))
            .replace("{{ROWS}}", "\n".join(rows))
        )
        output.write_text(document, encoding="utf-8")

    @staticmethod
    def _check_format(format_: str) -> None:
        if format_ not in SearchSettings.EXPORT_FORMATS:
            raise ValueError(f"format_ must be one of {SearchSettings.EXPORT_FORMATS}")

    @staticmethod
    def _write_table(
        output: Path,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        count_label: str,
    ) -> None:
        """Write an HTML table; each cell in `rows` is already-escaped HTML."""
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        document = (
            Export.template("list_export.html")
            .replace("{{PALETTE}}", Palette.css_variables())
            .replace("{{STYLE}}", Export.template("export.css").rstrip("\n"))
            .replace("{{APP_NAME}}", html.escape(APP_NAME))
            .replace("{{APP_TAGLINE}}", html.escape(APP_TAGLINE))
            .replace("{{TITLE}}", html.escape(title))
            .replace("{{COUNT}}", html.escape(count_label))
            .replace("{{GENERATED_AT}}", html.escape(Export._generated_at()))
            .replace("{{HEADERS}}", head)
            .replace("{{ROWS}}", body)
        )
        output.write_text(document, encoding="utf-8")

    @staticmethod
    def sources(sources: list[Source], output: Path, format_: str) -> None:
        """Write the registered `sources` (`vethuq source list`) to `output`."""
        Export._check_format(format_)
        if format_ == "json":
            payload = {
                "generated_at": Export._generated_at(),
                "source_count": len(sources),
                "sources": [source.to_dict() for source in sources],
            }
            output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return
        rows = [
            [
                str(s.id),
                html.escape(s.source_type),
                html.escape(s.status),
                f'<a href="{html.escape(Export._file_uri(s.path))}">{html.escape(s.path)}</a>',
                html.escape(s.added_at),
                html.escape(s.last_scanned_at or "-"),
            ]
            for s in sources
        ]
        Export._write_table(
            output,
            "Sources",
            ["ID", "Type", "Status", "Path", "Added", "Last Scanned"],
            rows,
            f"{len(sources)} source(s)",
        )

    @staticmethod
    def _file_name(source: Source, file: SourceFile) -> str:
        if source.source_type == "folder":
            try:
                return Path(file.file_path).relative_to(source.path).as_posix()
            except ValueError:
                pass
        return Path(file.file_path).name

    @staticmethod
    def source_files(
        source: Source, files: list[SourceFile], output: Path, format_: str, *, detail: bool
    ) -> None:
        """Write the `files` under `source` (`vethuq source list <source> [--detail]`)."""
        from vethuq_core.ocr import Deepening  # imported here: ocr itself imports source

        Export._check_format(format_)
        phase_name = Deepening.PHASE_NAMES

        if format_ == "json":
            entries: list[dict[str, object]] = []
            for file in files:
                entry: dict[str, object] = {
                    "id": file.id,
                    "file_name": Export._file_name(source, file),
                    "status": file.status,
                }
                if detail:
                    full = file.to_dict()
                    full.pop("id")
                    full.pop("status")
                    full["ocr_phase_name"] = phase_name.get(file.ocr_phase or 0)
                    entry.update(full)
                entries.append(entry)
            payload = {
                "generated_at": Export._generated_at(),
                "source": source.to_dict(),
                "file_count": len(files),
                "detail": detail,
                "files": entries,
            }
            output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return

        headers = ["ID", "File Name", "Status"]
        if detail:
            headers += [
                "Type",
                "Size",
                "Pages",
                "Started",
                "Completed",
                "Indexed",
                "Duration",
                "Confidence",
                "OCR Phase",
                "OCR Angles",
                "Deeper Phases",
                "Retries",
                "Duplicate Of",
                "Error",
            ]
        rows = []
        for file in files:
            row = [
                str(file.id),
                f'<a href="{html.escape(Export._file_uri(file.file_path))}">'
                f"{html.escape(Export._file_name(source, file))}</a>",
                html.escape(file.status),
            ]
            if detail:
                phase = "-"
                if file.ocr_phase is not None:
                    phase = phase_name.get(file.ocr_phase, str(file.ocr_phase))
                timings = "; ".join(
                    f"{phase_name.get(t.phase, t.phase)}: {t.started_at} - "
                    f"{t.completed_at or 'in progress'} ({t.duration_seconds:.1f}s)"
                    for t in file.phase_timings
                )
                cells = [
                    file.file_type,
                    Formatting.size(file.file_size_bytes),
                    str(file.pages) if file.pages else "-",
                    file.started_at or "-",
                    file.completed_at or "-",
                    file.indexed_at or "-",
                    f"{file.duration:.1f}s" if file.duration is not None else "-",
                    f"{file.confidence:.0%}" if file.confidence is not None else "-",
                    phase,
                    ", ".join(str(a) for a in file.ocr_angles) or "-",
                    timings or "-",
                    str(file.retry_count),
                    file.duplicate_of_path or "-",
                    file.error_message or "-",
                ]
                row += [html.escape(c) for c in cells]
            rows.append(row)
        Export._write_table(
            output,
            f"Files in {source.path}",
            headers,
            rows,
            f"{len(files)} file(s)",
        )
