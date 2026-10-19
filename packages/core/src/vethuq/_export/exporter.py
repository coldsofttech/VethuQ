"""Writing search results and source listings to a JSON or HTML file."""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from vethuq._export.facets import _Facets
from vethuq._export.languages import _ExportLanguages
from vethuq._export.page import _Page
from vethuq.formatting import Formatting

if TYPE_CHECKING:
    from vethuq.export import ExportSection
    from vethuq.search import SearchMatch, SearchResult
    from vethuq.sources import FileIndex, Source, SourceFile

# How an engine names a hit: its short badge, and whether it guesses (so its score is shown).
Badges = Callable[[], dict[str, tuple[str, bool]]]


class _Exporter:
    FORMATS = ("json", "html")

    def __init__(self, languages: _ExportLanguages, badges: Badges) -> None:
        self._languages = languages
        self._badges = badges

    # ----- shared -----------------------------------------------------------------------------

    @classmethod
    def check_format(cls, format_: str) -> str:
        if format_ not in cls.FORMATS:
            raise ValueError(f"format must be one of {', '.join(cls.FORMATS)}, not {format_!r}.")
        return format_

    @staticmethod
    def with_extension(output: Path, format_: str) -> Path:
        """`output` with `.format_` added when it has no extension of its own."""
        output = Path(output).expanduser()
        return output if output.suffix or output.is_dir() else output.with_name(f"{output.name}.{format_}")

    @staticmethod
    def _write(output: Path, text: str) -> Path:
        output = Path(output).expanduser()
        if output.is_dir():
            raise IsADirectoryError(f"{output} is a folder; name a file.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        return output

    @staticmethod
    def _json(payload: dict[str, object]) -> str:
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _file_uri(path: str) -> str:
        return Path(path).resolve().as_uri()

    def _tagged(self, text: str) -> str:
        """`text` escaped for HTML, with runs in other languages marked up."""
        return self._languages.tag(html.escape(text))

    # ----- search results ---------------------------------------------------------------------

    @staticmethod
    def _matched_text(match: SearchMatch) -> str:
        prefix = "..." if match.truncated_before else ""
        suffix = "..." if match.truncated_after else ""
        return f"{prefix}{match.before}{match.matched}{match.after}{suffix}"

    def _badge(self, match: SearchMatch) -> str:
        """How the match was found, as exports name it (`Exact`, `Similar 83%`), or ''."""
        found = self._badges().get(match.engine)
        if found is None:
            return ""
        badge, approximate = found
        if approximate and match.score is not None:
            return f"{badge} {match.score:.0%}"
        return badge

    def _match_entry(self, match: SearchMatch) -> dict[str, object]:
        text = self._matched_text(match)
        entry: dict[str, object] = {
            "file_name": match.file_name,
            "file_path": match.file_path,
            "page_number": match.page_number,
            "total_pages": match.total_pages,
            "matched_text": text,
            "languages": self._languages.in_text(text),
            "engine": match.engine,
        }
        badge = self._badge(match)
        if badge:
            entry["match_type"] = badge
        if match.duplicate_of_path:
            entry["duplicate_of_path"] = match.duplicate_of_path
        if match.matched_by:
            entry["matched_by"] = list(match.matched_by)
        if match.modifiers:
            entry["modifiers"] = list(match.modifiers)
        if match.score is not None:
            entry["score"] = match.score
        return entry

    def _languages_used(self, result: SearchResult) -> list[str]:
        used = self._languages.in_text(result.query)
        for match in result.matches:
            for language_id in self._languages.in_text(self._matched_text(match)):
                if language_id not in used:
                    used.append(language_id)
        return self._languages.ordered(used)

    @staticmethod
    def _settings(result: SearchResult) -> list[tuple[str, str]]:
        """How the search was run, as (label, value): enough to run it again."""
        rows = [("Engine", result.engine)]
        if result.engine != "all" and len(result.levels) == 1:
            ((_, levels),) = result.levels.items()
            if levels:
                rows.append(("Normalization", ", ".join(f"{k}={v}" for k, v in levels.items())))
        for engine, values in result.options.items():
            for name, value in values.items():
                rows.append((f"{engine} {name}", value))
        if result.pending:
            rows.append(
                ("Not prepared", ", ".join(f"{e}: {n} pages" for e, n in result.pending.items()))
            )
        return rows

    def search_results(self, result: SearchResult, output: Path, format_: str) -> Path:
        """Write the matches of `result` to `output` as `format_` ('json' or 'html')."""
        self.check_format(format_)
        output = self.with_extension(output, format_)
        if format_ == "json":
            return self._write(output, self._json(self._search_payload(result)))
        return self._write(output, self._search_html(result))

    def _search_payload(self, result: SearchResult) -> dict[str, object]:
        entries = [self._match_entry(match) for match in result.matches]
        payload: dict[str, object] = {
            "query": result.query,
            "engine": result.engine,
            "levels": {engine: dict(levels) for engine, levels in result.levels.items()},
        }
        if result.options:
            payload["options"] = {engine: dict(values) for engine, values in result.options.items()}
        if result.pending:
            payload["pending"] = dict(result.pending)
        payload["query_languages"] = self._languages.in_text(result.query)
        payload["languages"] = self._languages.ordered(
            [lang for entry in entries for lang in entry["languages"]]  # type: ignore[union-attr]
        )
        payload["generated_at"] = _Page.generated_at()
        payload["total"] = result.total
        payload["result_count"] = len(entries)
        payload["matches"] = entries
        return payload

    def _search_html(self, result: SearchResult) -> str:
        used = self._languages_used(result)
        chips = [_Page.chip(label, value) for label, value in self._settings(result)]
        if used:
            chips.append(_Page.chip("Languages", self._languages.names(used)))
        matches = result.matches
        cards = [
            _Page.card("Matches", str(len(matches))),
            _Page.card("Files", str(len({m.file_path for m in matches})), accent=True),
        ]
        if result.total != len(matches):
            cards.append(_Page.card("Of all matches", str(result.total)))
        bar, attrs = _Facets.bar(
            [
                ("engine", "Match type"),
                ("type", "File type"),
                ("language", "Language"),
                ("origin", "Text from"),
                ("folder", "Folder"),
            ],
            [self._match_facets(match) for match in matches],
            self._languages.tag,
        )
        rows = [self._search_row(match, attr) for match, attr in zip(matches, attrs, strict=True)]
        document = (
            _Page.template("export.html")
            .replace("{{QUERY_TEXT}}", html.escape(result.query))
            .replace("{{QUERY}}", self._tagged(result.query))
            .replace("{{CARDS}}", "\n".join(cards))
            .replace("{{CHIPS}}", "".join(chips))
            .replace("{{FACETS}}", bar)
            .replace("{{ROWS}}", "\n".join(rows))
        )
        return _Page.fill(
            document,
            kind="Search export",
            lang=self._languages.document(used),
            generated_at=_Page.generated_at(),
        )

    ORIGINS = {"native": "Native text", "ocr": "OCR", "mixed": "Native + OCR"}

    def _match_facets(self, match: SearchMatch) -> dict[str, list[str]]:
        """The values `match` is filtered by in the HTML export."""
        path = Path(match.file_path)
        facets = {
            "type": [path.suffix.lstrip(".").upper() or "(none)"],
            "folder": [path.parent.as_posix()],
            "origin": [self.ORIGINS.get(match.source, match.source)],
            "language": [
                self._languages.names([language_id])
                for language_id in self._languages.in_text(self._matched_text(match))
            ],
        }
        found = self._badges().get(match.engine)
        if found is not None:
            facets["engine"] = [found[0]]
        return facets

    def _search_row(self, match: SearchMatch, facets: str = "") -> str:
        page = str(match.page_number) if match.page_number is not None else "-"
        total = str(match.total_pages) if match.total_pages is not None else "-"
        snippet = self._tagged(self._matched_text(match)).replace(
            html.escape(match.matched), f"<mark>{html.escape(match.matched)}</mark>", 1
        )
        badge = self._badge(match)
        pill = f'<span class="pill">{html.escape(badge)}</span>' if badge else ""
        return (
            _Page.template("export_row.html")
            .replace("{{FACETS}}", facets)
            .replace("{{FILE_URI}}", html.escape(self._file_uri(match.file_path)))
            .replace("{{FILE_NAME}}", self._tagged(match.file_name))
            .replace("{{FILE_PATH}}", self._tagged(match.file_path))
            .replace("{{PAGE}}", page)
            .replace("{{TOTAL_PAGES}}", total)
            .replace("{{MATCH}}", pill)
            .replace("{{SNIPPET}}", snippet)
        )

    # ----- listings ---------------------------------------------------------------------------

    Facets = tuple[list[tuple[str, str]], list[dict[str, list[str]]]]

    def _table(
        self,
        output: Path,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        cards: list[str],
        facets: Facets = ([], []),
    ) -> Path:
        """Write an HTML table under summary `cards`; each `rows` cell is escaped HTML. `facets`
        are the `(key, label)` filters and each row's values for them."""
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        bar, attrs = _Facets.bar(*facets, self._languages.tag)
        body = "\n".join(
            f"<tr {attr}>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
            for row, attr in zip(rows, attrs or [""] * len(rows), strict=True)
        )
        document = (
            _Page.template("list_export.html")
            .replace("{{TITLE}}", html.escape(title))
            .replace("{{CARDS}}", "\n".join(cards))
            .replace("{{FACETS}}", bar)
            .replace("{{HEADERS}}", head)
            .replace("{{ROWS}}", body)
        )
        default = self._languages.default()
        document = _Page.fill(
            document,
            kind="List export",
            lang=default.id if default else "en",
            generated_at=_Page.generated_at(),
        )
        return self._write(output, document)

    def sources(self, sources: list[Source], output: Path, format_: str) -> Path:
        """Write the registered `sources` to `output`."""
        self.check_format(format_)
        output = self.with_extension(output, format_)
        if format_ == "json":
            payload = {
                "generated_at": _Page.generated_at(),
                "source_count": len(sources),
                "sources": [source.to_dict() for source in sources],
            }
            return self._write(output, self._json(payload))
        rows = [
            [
                str(s.id),
                html.escape(s.source_type.value if s.source_type else "-"),
                _Page.status_pill(s.status.value if s.status else "-"),
                f'<a href="{html.escape(self._file_uri(s.path))}">{self._tagged(s.path)}</a>',
                html.escape(s.progress or "-"),
                html.escape(", ".join(s.languages) if s.languages else "-"),
                html.escape(s.added_at or "-"),
                html.escape(s.last_scanned_at or "-"),
            ]
            for s in sources
        ]
        return self._table(
            output,
            "Sources",
            ["ID", "Type", "Status", "Path", "Progress", "Languages", "Added", "Last Scanned"],
            rows,
            [
                _Page.card("Sources", str(len(sources))),
                _Page.card(
                    "Folders",
                    str(
                        sum(
                            s.source_type is not None and s.source_type.value == "folder"
                            for s in sources
                        )
                    ),
                    accent=True,
                ),
            ],
            (
                [("type", "Type"), ("status", "Status")],
                [
                    {
                        "type": [s.source_type.value if s.source_type else "-"],
                        "status": [s.status.value if s.status else "-"],
                    }
                    for s in sources
                ],
            ),
        )

    @staticmethod
    def _percent(value: float | None) -> str:
        return f"{value:.0%}" if value is not None else "-"

    def source_files(
        self, source: Source, files: list[SourceFile], output: Path, format_: str
    ) -> Path:
        """Write the `files` of `source` to `output`. Files that carry their `index` (listed with
        `detailed=True`) get the indexing columns too."""
        self.check_format(format_)
        output = self.with_extension(output, format_)
        detailed = any(f.index is not None for f in files)
        if format_ == "json":
            payload = {
                "generated_at": _Page.generated_at(),
                "source": source.to_dict(),
                "file_count": len(files),
                "detail": detailed,
                "files": [f.to_dict() for f in files],
            }
            return self._write(output, self._json(payload))

        headers = ["File Name", "Size", "Modified"]
        if detailed:
            headers += [
                "Status",
                "Type",
                "Pages",
                "Confidence",
                "Band",
                "Low-confidence Pages",
                "Languages",
                "Indexed",
                "Retries",
                "Duplicate Of",
                "Error",
            ]
        rows = []
        for file in files:
            row = [
                f'<a href="{html.escape(self._file_uri(file.path))}">'
                f"{self._tagged(file.relative_path)}</a>",
                html.escape(Formatting.size(file.size_bytes)),
                html.escape(file.modified_at),
            ]
            if detailed:
                row += self._index_cells(file.index)
            rows.append(row)
        statuses = [f.index.status.value for f in files if f.index is not None]
        return self._table(
            output,
            f"Files in {source.path}",
            headers,
            rows,
            [
                _Page.card("Files", str(len(files))),
                _Page.card("Indexed", str(statuses.count("indexed")), accent=True),
                _Page.card("Failed", str(statuses.count("error"))),
            ],
            (
                [("status", "Status"), ("type", "File type"), ("duplicate", "Duplicate")],
                [self._file_facets(f, detailed) for f in files],
            ),
        )

    @staticmethod
    def _file_facets(file: SourceFile, detailed: bool) -> dict[str, list[str]]:
        """The values a file is filtered by (its index state only when it was listed in detail)."""
        index = file.index
        kind = (index.file_type if index and index.file_type else Path(file.name).suffix[1:]) or "-"
        facets = {"type": [kind.upper()]}
        if detailed and index is not None:
            facets["status"] = [index.status.value]
            facets["duplicate"] = ["Duplicate" if index.duplicate_of else "Unique"]
        return facets

    def _index_cells(self, index: FileIndex | None) -> list[str]:
        if index is None:
            return ["-"] * 11
        return [
            _Page.status_pill(index.status.value),
            html.escape(index.file_type or "-"),
            html.escape(str(index.pages) if index.pages else "-"),
            html.escape(self._percent(index.confidence)),
            html.escape(index.band.value if index.band else "-"),
            html.escape(
                str(index.low_confidence_pages) if index.low_confidence_pages is not None else "-"
            ),
            html.escape(", ".join(index.languages) if index.languages else "-"),
            html.escape(index.indexed_at or "-"),
            html.escape(str(index.retry_count)),
            html.escape(index.duplicate_of or "-"),
            html.escape(index.error or "-"),
        ]

    # ----- any listing ------------------------------------------------------------------------

    def _cell(
        self,
        name: str,
        record: dict[str, object],
        statuses: tuple[str, ...],
        paths: tuple[str, ...],
        formats: dict[str, Callable[[object], str]],
    ) -> str:
        value = record.get(name)
        if name in formats and value is not None:
            return formats[name](value)
        text = "-" if value is None or value == "" else str(value)
        if name in statuses and value:
            return _Page.status_pill(text)
        if name in paths and value:
            return f'<a href="{html.escape(self._file_uri(text))}">{self._tagged(text)}</a>'
        return self._tagged(text)

    @staticmethod
    def _facet_values(record: dict[str, object], fields: tuple[str, ...]) -> dict[str, list[str]]:
        return {f: [str(record[f])] for f in fields if record.get(f) not in (None, "")}

    def records(
        self,
        records: list[dict[str, object]],
        columns: list[tuple[str, str]],
        output: Path,
        format_: str,
        *,
        title: str,
        key: str,
        statuses: tuple[str, ...] = (),
        paths: tuple[str, ...] = (),
        facets: tuple[str, ...] = (),
        cards: list[tuple[str, str]] | None = None,
        formats: dict[str, Callable[[object], str]] | None = None,
    ) -> Path:
        """Write any listing - `records` shown under `columns` - to `output`, as JSON or HTML.

        `columns` are `(field, header)` in display order. JSON holds the records as they are under
        `key`. In HTML a field in `statuses` is a colored pill, one in `paths` a link to the file,
        and a field in `facets` a filter (left out when it has fewer than two values). A `None`
        shows as `-`; `formats` maps a field to a function giving its cell's HTML (it must
        escape). `cards` are extra `(label, value)` summary cards after the row count.
        """
        self.check_format(format_)
        output = self.with_extension(output, format_)
        if format_ == "json":
            payload = {
                "generated_at": _Page.generated_at(),
                "title": title,
                "count": len(records),
                key: records,
            }
            return self._write(output, self._json(payload))
        headers = dict(columns)
        rows = [
            [self._cell(f, record, statuses, paths, formats or {}) for f, _ in columns]
            for record in records
        ]
        return self._table(
            output,
            title,
            [header for _, header in columns],
            rows,
            [
                _Page.card(title, str(len(records))),
                *(_Page.card(label, value) for label, value in cards or []),
            ],
            (
                [(field, headers[field]) for field in facets],
                [self._facet_values(record, facets) for record in records],
            ),
        )

    def sections(
        self,
        sections: list[ExportSection],
        output: Path,
        format_: str,
        *,
        title: str,
        cards: list[tuple[str, str]] | None = None,
    ) -> Path:
        """Write several listings - one table each - to one JSON or HTML file.

        JSON has each section's records under its `key`, plus a `counts` object. HTML has a
        summary card per section (and any extra `cards`), then each table under its own heading
        with its own filters; a section with no records says so instead of showing a table.
        """
        self.check_format(format_)
        output = self.with_extension(output, format_)
        if format_ == "json":
            payload: dict[str, object] = {
                "generated_at": _Page.generated_at(),
                "title": title,
                "counts": {s.key: len(s.records) for s in sections},
            }
            payload.update({s.key: s.records for s in sections})
            return self._write(output, self._json(payload))
        blocks = []
        for section in sections:
            if not section.records:
                body = f'<p class="empty">{html.escape(section.empty)}</p>'
            else:
                headers = dict(section.columns)
                bar, attrs = _Facets.bar(
                    [(f, headers[f]) for f in section.facets],
                    [self._facet_values(r, section.facets) for r in section.records],
                    self._languages.tag,
                )
                head = "".join(f"<th>{html.escape(h)}</th>" for _, h in section.columns)
                rows = "\n".join(
                    f"<tr {attr}>"
                    + "".join(
                        "<td>"
                        + self._cell(f, record, section.statuses, section.paths, section.formats)
                        + "</td>"
                        for f, _ in section.columns
                    )
                    + "</tr>"
                    for record, attr in zip(section.records, attrs, strict=True)
                )
                body = (
                    f"{bar}\n"
                    '<div class="results table-wrap"><table class="list">'
                    f"<thead><tr>{head}</tr></thead>\n<tbody>\n{rows}\n</tbody></table></div>"
                )
            blocks.append(
                _Page.template("section.html")
                .replace("{{SECTION_TITLE}}", html.escape(section.title))
                .replace("{{BODY}}", body)
            )
        document = (
            _Page.template("sections_export.html")
            .replace("{{TITLE}}", html.escape(title))
            .replace(
                "{{CARDS}}",
                "\n".join(
                    [_Page.card(s.title, str(len(s.records))) for s in sections]
                    + [_Page.card(label, value) for label, value in cards or []]
                ),
            )
            .replace("{{SECTIONS}}", "\n".join(blocks))
        )
        default = self._languages.default()
        document = _Page.fill(
            document,
            kind="List export",
            lang=default.id if default else "en",
            generated_at=_Page.generated_at(),
        )
        return self._write(output, document)
