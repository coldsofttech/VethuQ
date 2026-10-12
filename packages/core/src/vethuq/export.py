"""Write any listing, or several, to a JSON or HTML file.

    from vethuq.export import ExportSection

    client.export.records(rows, [("id", "ID"), ("status", "Status")], "out.html", title="Jobs",
                          key="jobs", statuses=("status",), facets=("status",))

Search results and source listings have their own `export` (`client.search.export`,
`client.sources.export`); this is for everything else: the command line uses it for its lists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vethuq._db import _Database
from vethuq._export import _Exporter
from vethuq._settings import _SearchSettings
from vethuq.enums import ExportFormat

__all__ = ["Export", "ExportSection"]


@dataclass
class ExportSection:
    """One table of a multi-table export (`Export.sections`).

    `columns` are `(field, header)` in display order. In HTML a field in `statuses` is a colored
    pill, one in `paths` a link to the file, one in `facets` a filter, and `formats` maps a field
    to a function giving its cell's HTML (it must escape); JSON keeps the raw `records`.
    """

    title: str
    key: str
    columns: list[tuple[str, str]]
    records: list[dict[str, object]]
    statuses: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    facets: tuple[str, ...] = ()
    formats: dict[str, Callable[[object], str]] = field(default_factory=dict)
    empty: str = "Nothing to show."


class Export:
    """Write listings to a file.

    Not created directly: use `VethuQ().export`.
    """

    def __init__(self, database: _Database, exporter: _Exporter) -> None:
        self._database = database
        self._exporter = exporter

    def _format(self, format_: ExportFormat | str | None) -> str:
        if format_ is None:
            with self._database.session() as session:
                return _SearchSettings.get_export_format(session)
        return _Exporter.check_format(str(getattr(format_, "value", format_)).strip().lower())

    def records(
        self,
        records: list[dict[str, object]],
        columns: list[tuple[str, str]],
        output: str | Path,
        format: ExportFormat | str | None = None,
        *,
        title: str,
        key: str,
        statuses: tuple[str, ...] = (),
        paths: tuple[str, ...] = (),
        facets: tuple[str, ...] = (),
        cards: list[tuple[str, str]] | None = None,
        formats: dict[str, Callable[[object], str]] | None = None,
    ) -> Path:
        """Write a listing - `records` shown under `columns` - to `output` and return its path.

        `columns` are `(field, header)` in display order. `format` is `json` or `html`; left out,
        the saved default (`settings.search`, `json`). JSON holds the records as they are under
        `key`. In HTML a field in `statuses` is a colored pill, one in `paths` a link to the
        file, and a field in `facets` a filter (left out when it has fewer than two values); a
        `None` shows as `-`, and `formats` maps a field to a function giving its cell's HTML
        (it must escape). `cards` are extra `(label, value)` summary cards after the row count.

        Raises `ValueError` for a format that isn't `json` or `html`, a `facets` field that is
        not a column, and `IsADirectoryError` if `output` is a folder.
        """
        known = {name for name, _ in columns}
        if unknown := [f for f in facets if f not in known]:
            raise ValueError(f"facets must be columns: {', '.join(unknown)}.")
        return self._exporter.records(
            records,
            columns,
            Path(output),
            self._format(format),
            title=title,
            key=key,
            statuses=statuses,
            paths=paths,
            facets=facets,
            cards=cards,
            formats=formats,
        )

    def sections(
        self,
        sections: list[ExportSection],
        output: str | Path,
        format: ExportFormat | str | None = None,
        *,
        title: str,
        cards: list[tuple[str, str]] | None = None,
    ) -> Path:
        """Write several listings - one table each - to one file and return its path.

        JSON has each section's records under its `key`, plus a `counts` object. HTML has a
        summary card per section (and any extra `cards`), then each table under its own heading
        with its own filters; a section with no records says so instead of showing a table.
        """
        for section in sections:
            known = {name for name, _ in section.columns}
            if unknown := [f for f in section.facets if f not in known]:
                raise ValueError(f"{section.title}: facets must be columns: {', '.join(unknown)}.")
        return self._exporter.sections(
            sections, Path(output), self._format(format), title=title, cards=cards
        )
