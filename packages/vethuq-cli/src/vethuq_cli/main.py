"""VethuQ CLI entry point."""

from __future__ import annotations

import typer

from vethuq_cli.source import app as source_app

app = typer.Typer(help="VethuQ — document intelligence and evidence infrastructure.")
app.add_typer(source_app, name="source")


if __name__ == "__main__":
    app()
