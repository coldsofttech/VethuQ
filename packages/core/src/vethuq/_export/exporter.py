"""Writing search results and source listings to a JSON or HTML file."""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from vethuq._export.languages import _ExportLanguages
from vethuq._export.page import _Page

if TYPE_CHECKING:
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
        rows = [self._search_row(match) for match in matches]
        document = (
            _Page.template("export.html")
            .replace("{{QUERY_TEXT}}", html.escape(result.query))
            .replace("{{QUERY}}", self._tagged(result.query))
            .replace("{{CARDS}}", "\n".join(cards))
            .replace("{{CHIPS}}", "".join(chips))
            .replace("{{SCRIPT}}", f"<script>\n{_Page.template('export.js').rstrip()}\n</script>")
            .replace("{{ROWS}}", "\n".join(rows))
        )
        return _Page.fill(
            document,
            kind="Search export",
            lang=self._languages.document(used),
            generated_at=_Page.generated_at(),
        )

    def _search_row(self, match: SearchMatch) -> str:
        page = str(match.page_number) if match.page_number is not None else "-"
        total = str(match.total_pages) if match.total_pages is not None else "-"
        snippet = self._tagged(self._matched_text(match)).replace(
            html.escape(match.matched), f"<mark>{html.escape(match.matched)}</mark>", 1
        )
        badge = self._badge(match)
        pill = f'<span class="pill">{html.escape(badge)}</span>' if badge else ""
        return (
            _Page.template("export_row.html")
            .replace("{{FILE_URI}}", html.escape(self._file_uri(match.file_path)))
            .replace("{{FILE_NAME}}", self._tagged(match.file_name))
            .replace("{{FILE_PATH}}", self._tagged(match.file_path))
            .replace("{{PAGE}}", page)
            .replace("{{TOTAL_PAGES}}", total)
            .replace("{{MATCH}}", pill)
            .replace("{{SNIPPET}}", snippet)
        )

    # ----- listings ---------------------------------------------------------------------------

    def _table(
        self, output: Path, title: str, headers: list[str], rows: list[list[str]], cards: list[str]
    ) -> Path:
        """Write an HTML table under summary `cards`; each `rows` cell is escaped HTML."""
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        document = (
            _Page.template("list_export.html")
            .replace("{{TITLE}}", html.escape(title))
            .replace("{{CARDS}}", "\n".join(cards))
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
        )

    @staticmethod
    def _size(count: int) -> str:
        size = float(count)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{count} B"

    @staticmethod
    def _percent(value: float | None) -> str:
        return f"{value:.0%}" if value is not None else "-"

    def source_files(
        self, source: Source, files: list[SourceFile], output: Path, format_: str
    ) -> Path:
        """Write the `files` of `source` to `output`. Files that carry their `index` (listed with
        `detailed=True`) get the indexing columns too."""
        self.check_format(format_)
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
                html.escape(self._size(file.size_bytes)),
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
        )

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
