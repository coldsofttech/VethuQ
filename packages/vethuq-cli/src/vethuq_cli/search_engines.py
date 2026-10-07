"""`vethuq search-engines ...` commands: which search engines this install has."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.search.engines.catalog import SearchEngineCatalog, SearchEngineInfo
from vethuq_core.settings.filetypes import FileTypeSettings
from vethuq_core.storage import open_storage

from vethuq_cli.console import console
from vethuq_cli.export import ListExport
from vethuq_cli.theme import Theme

app = typer.Typer(help="Show which search engines are installed.")


class EnginesTable:
    @staticmethod
    def status(engine: SearchEngineInfo) -> Text:
        if not engine.is_installed():
            return Text("not installed", style=Theme.WARNING)
        if not SearchEngineCatalog.is_enabled(engine):
            return Text("installed, not enabled", style=Theme.NOTICE)
        return Text("installed (default)" if engine.default else "installed", style=Theme.OK)

    @staticmethod
    def build(engines: list[SearchEngineInfo], *, show_hints: bool) -> Table:
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("Engine", "Name", "Package", "Status"):
            table.add_column(column)
        if show_hints:
            table.add_column("Install")
        for engine in engines:
            row = [
                Text(engine.id, style="bold"),
                Text(engine.label, style="white"),
                Text(engine.extra, style="white"),
                EnginesTable.status(engine),
            ]
            if show_hints:
                row.append(
                    Text("" if engine.is_installed() else engine.install_hint, style="white")
                )
            table.add_row(*row)
        return table


@app.command("list")
def list_engines(
    all_engines: bool = typer.Option(
        False,
        "--all",
        help="Also list search engines that are not installed, with the command to install each.",
    ),
    export: ListExport.EXPORT = None,
    format_: ListExport.FORMAT = None,
) -> None:
    """List the installed search engines.

    The default engine is `like`; add others with pip (`pip install vethuq[search-exact]`) or
    by re-running the installer - there is no enable/disable switch here.
    """
    export_target = ListExport.resolve(export, format_)
    engines = list(SearchEngineCatalog.all() if all_engines else SearchEngineCatalog.installed())
    storage = open_storage()
    try:
        FileTypeSettings.record_installed_engines(storage)
    finally:
        storage.close()
    if export_target is not None:
        ListExport.write(
            export_target,
            [
                {
                    "id": e.id,
                    "name": e.label,
                    "package": e.extra,
                    "status": EnginesTable.status(e).plain,
                    "install": "" if e.is_installed() else e.install_hint,
                }
                for e in engines
            ],
            [
                ("id", "Engine"),
                ("name", "Name"),
                ("package", "Package"),
                ("status", "Status"),
                ("install", "Install"),
            ],
            title="Search engines",
            key="search_engines",
            noun="search engine(s)",
            statuses=("status",),
            facets=("status",),
        )
        return
    console.print(
        Panel(
            EnginesTable.build(engines, show_hints=all_engines),
            title=Text("Search engines"),
            title_align="left",
            border_style=Theme.PRIMARY,
            expand=True,
        )
    )
