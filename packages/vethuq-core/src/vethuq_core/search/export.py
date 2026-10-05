"""Export `search` results and `source list` output to a JSON or HTML file."""

from __future__ import annotations

import base64
import functools
import html
import json
import locale
import re
from datetime import datetime
from importlib import resources
from pathlib import Path

from vethuq_core.branding import APP_NAME, APP_TAGLINE, Palette
from vethuq_core.formatting import Formatting
from vethuq_core.languages.scripts import Scripts
from vethuq_core.ocr.catalog import OcrCatalog
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
    def logo() -> str:
        """The logo as inline `<svg class="logo">`, so the export stays one portable file."""
        return (
            Export.template("logo.svg")
            .strip()
            .replace("<svg ", '<svg class="logo" ', 1)
            .replace(' width="512" height="512"', ' role="img" aria-label="logo"', 1)
        )

    @staticmethod
    def _favicon() -> str:
        """The logo as a `data:` URI for the browser tab."""
        data = base64.b64encode(Export.template("logo.svg").encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{data}"

    @staticmethod
    def _fill_page(document: str, *, kind: str, lang: str, generated_at: str) -> str:
        """Fill the parts every export shares: head, brand header (logo, name, tagline), footer."""
        shared = {
            "{{HEAD}}": Export.template("page_head.html").rstrip("\n"),
            "{{HEADER}}": Export.template("page_header.html").rstrip("\n"),
            "{{FOOTER}}": Export.template("page_footer.html").rstrip("\n"),
        }
        for placeholder, text in shared.items():
            document = document.replace(placeholder, text)
        return (
            document.replace("{{LANG}}", lang)
            .replace("{{FAVICON}}", Export._favicon())
            .replace("{{PALETTE}}", Palette.css_variables())
            .replace("{{STYLE}}", Export.template("export.css").rstrip("\n"))
            .replace("{{LOGO}}", Export.logo())
            .replace("{{KIND}}", html.escape(kind))
            .replace("{{APP_NAME}}", html.escape(APP_NAME))
            .replace("{{APP_TAGLINE}}", html.escape(APP_TAGLINE))
            .replace("{{GENERATED_AT}}", html.escape(generated_at))
        )

    @staticmethod
    def _card(label: str, value: str, *, accent: bool = False) -> str:
        css = "card accent" if accent else "card"
        return (
            f'<div class="{css}"><div class="label">{html.escape(label)}</div>'
            f'<div class="value">{html.escape(value)}</div></div>'
        )

    @staticmethod
    def _chip(label: str, value: str) -> str:
        key = f'<span class="k">{html.escape(label)}</span>'
        return f'<span class="chip">{key}{html.escape(value)}</span>'

    @staticmethod
    def _status_pill(status: str) -> str:
        """A file or source status as a colored pill (green done, amber in flight, red failed)."""
        kind = {
            "indexed": "ok",
            "ready": "ok",
            "active": "ok",
            "pending": "warn",
            "processing": "warn",
            "running": "warn",
            "paused": "warn",
            "failed": "bad",
            "error": "bad",
            "missing": "bad",
            "removed": "muted",
        }.get(status, "muted")
        return f'<span class="pill {kind}">{html.escape(status)}</span>'

    @staticmethod
    def languages_in(text: str) -> list[str]:
        """The ids of the languages `text` is written in, judged by script, in catalog order.

        Every language the catalog knows counts, installed or not: a file read when Telugu was
        installed still is Telugu in an export made after it was removed. Text with no letters of
        any known script (digits, punctuation) is in no language.
        """
        present = Scripts.present(text)
        return [lang.id for lang in OcrCatalog.languages() if lang.script in present]

    @staticmethod
    def _document_language(ids: list[str]) -> str:
        """The `<html lang>`: the one language used, else English (the rest are tagged inline)."""
        return ids[0] if len(ids) == 1 else OcrCatalog.default_language().id

    @staticmethod
    def _language_names(ids: list[str]) -> str:
        names = []
        for language_id in ids:
            info = OcrCatalog.language(language_id)
            names.append(info.label if info else language_id)
        return ", ".join(names)

    @staticmethod
    def _tagged(escaped: str) -> str:
        """Wrap each run of non-default-language text in `<span lang="..">`, so a browser picks
        that language's font and shaping inside an English page. `escaped` is already HTML-safe;
        English text is returned untouched."""
        default_script = OcrCatalog.default_language().script
        for lang in OcrCatalog.languages():
            script = Scripts.get(lang.script)
            if script is None or lang.script == default_script:
                continue
            body = "".join(f"{chr(a)}-{chr(b)}" for a, b in script.ranges)
            joiners = Scripts.JOINERS
            run = re.compile(f"[{body}][{body}{joiners} ]*(?<! )")
            tag = f'<span lang="{lang.id}">\\g<0></span>'
            escaped = run.sub(tag, escaped)
        return escaped

    @staticmethod
    def _match_type(match: SearchMatch) -> str:
        """How the match was found, as the CLI and UI name it (`Exact`, `Similar 83%`), or ''."""
        return Ranking.hit_badge(match) if match.engine in Ranking.BADGES else ""

    @staticmethod
    def _match_pill(match: SearchMatch) -> str:
        kind = Export._match_type(match)
        return f'<span class="pill">{html.escape(kind)}</span>' if kind else ""

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
            "languages": Export.languages_in(Export._matched_text(match)),
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
    def _union(entries: list[dict[str, object]]) -> list[str]:
        """The languages of all the matches, in catalog order."""
        found: set[str] = set()
        for entry in entries:
            found.update(entry["languages"])  # type: ignore[arg-type]
        return [lang.id for lang in OcrCatalog.languages() if lang.id in found]

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
        entries = [Export._match_entry(match) for match in matches]
        payload["query_languages"] = Export.languages_in(query)
        payload["languages"] = Export._union(entries)
        payload["generated_at"] = Export._generated_at()
        payload["result_count"] = len(matches)
        payload["matches"] = entries
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
        chips = []
        if engine is not None:
            chips.append(Export._chip("Engine", engine))
            if case_sensitive:
                chips.append(Export._chip("Case", "sensitive"))
            if threshold is not None:
                chips.append(Export._chip("Threshold", f"{threshold:.0%}"))
            if distance is not None:
                chips.append(Export._chip("Within", f"{distance} words"))
            if level is not None:
                chips.append(Export._chip("Leet level", level))
            if noise is not None:
                chips.append(Export._chip("Noise", noise))
            if unicode is not None and unicode != "off":
                chips.append(Export._chip("Unicode", unicode))
        used = Export.languages_in(query)
        for match in matches:
            for language_id in Export.languages_in(Export._matched_text(match)):
                if language_id not in used:
                    used.append(language_id)
        used = [lang.id for lang in OcrCatalog.languages() if lang.id in used]
        if used:
            chips.append(Export._chip("Languages", Export._language_names(used)))
        cards = [
            Export._card("Matches", str(len(matches))),
            Export._card("Files", str(len({m.file_path for m in matches})), accent=True),
        ]
        rows = []
        for match in matches:
            page = str(match.page_number) if match.page_number is not None else "-"
            total_pages = str(match.total_pages) if match.total_pages is not None else "-"
            snippet = Export._tagged(
                html.escape(Export._matched_text(match)).replace(
                    html.escape(match.matched), f"<mark>{html.escape(match.matched)}</mark>", 1
                )
            )
            row = (
                Export.template("export_row.html")
                .replace("{{FILE_URI}}", html.escape(Export._file_uri(match.file_path)))
                .replace("{{FILE_NAME}}", Export._tagged(html.escape(match.file_name)))
                .replace("{{FILE_PATH}}", Export._tagged(html.escape(match.file_path)))
                .replace("{{PAGE}}", page)
                .replace("{{TOTAL_PAGES}}", total_pages)
                .replace("{{MATCH}}", Export._match_pill(match))
                .replace("{{SNIPPET}}", snippet)
            )
            rows.append(row)

        document = (
            Export.template("export.html")
            .replace("{{QUERY_TEXT}}", html.escape(query))
            .replace("{{QUERY}}", Export._tagged(html.escape(query)))
            .replace("{{CARDS}}", "\n".join(cards))
            .replace("{{CHIPS}}", "".join(chips))
            .replace("{{SCRIPT}}", f"<script>\n{Export.template('export.js').rstrip()}\n</script>")
            .replace("{{ROWS}}", "\n".join(rows))
        )
        document = Export._fill_page(
            document,
            kind="Search export",
            lang=Export._document_language(used),
            generated_at=Export._generated_at(),
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
        cards: list[str],
    ) -> None:
        """Write an HTML table under summary `cards`; each `rows` cell is escaped HTML."""
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        document = (
            Export.template("list_export.html")
            .replace("{{TITLE}}", html.escape(title))
            .replace("{{CARDS}}", "\n".join(cards))
            .replace("{{HEADERS}}", head)
            .replace("{{ROWS}}", body)
        )
        document = Export._fill_page(
            document, kind="List export", lang="en", generated_at=Export._generated_at()
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
            output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return
        rows = [
            [
                str(s.id),
                html.escape(s.source_type),
                Export._status_pill(s.status),
                f'<a href="{html.escape(Export._file_uri(s.path))}">'
                f"{Export._tagged(html.escape(s.path))}</a>",
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
            [
                Export._card("Sources", str(len(sources))),
                Export._card(
                    "Folders", str(sum(s.source_type == "folder" for s in sources)), accent=True
                ),
            ],
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
            output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
                f"{Export._tagged(html.escape(Export._file_name(source, file)))}</a>",
                Export._status_pill(file.status),
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
            [
                Export._card("Files", str(len(files))),
                Export._card(
                    "Indexed", str(sum(f.status == "indexed" for f in files)), accent=True
                ),
                Export._card("Failed", str(sum(f.status in ("failed", "error") for f in files))),
            ],
        )
