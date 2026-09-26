"""VethuQ CLI entry point."""

from __future__ import annotations

import typer

from vethuq_cli.index import app as index_app
from vethuq_cli.search import search as search_command
from vethuq_cli.settings import app as settings_app
from vethuq_cli.source import app as source_app

app = typer.Typer(help="VethuQ — document intelligence and evidence infrastructure.")
app.add_typer(source_app, name="source")
app.add_typer(index_app, name="index")
app.add_typer(settings_app, name="settings")
app.command("search")(search_command)


if __name__ == "__main__":
    app()
