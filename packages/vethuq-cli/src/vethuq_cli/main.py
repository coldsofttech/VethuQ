"""VethuQ CLI entry point."""

from __future__ import annotations

import typer
from vethuq_core.branding import APP_NAME, APP_TAGLINE

from vethuq_cli.index import app as index_app
from vethuq_cli.interactive import run_interactive
from vethuq_cli.search import search as search_command
from vethuq_cli.settings import app as settings_app
from vethuq_cli.source import app as source_app
from vethuq_cli.stats import app as stats_app

app = typer.Typer(help=f"{APP_NAME} — {APP_TAGLINE}")
app.add_typer(source_app, name="source")
app.add_typer(index_app, name="index")
app.add_typer(settings_app, name="settings")
app.add_typer(stats_app, name="stats")
app.command("search")(search_command)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Run a subcommand, or launch the interactive console when none is given."""
    if ctx.invoked_subcommand is None:
        run_interactive()


if __name__ == "__main__":
    app()
