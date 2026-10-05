"""VethuQ CLI entry point."""

from __future__ import annotations

import sys
import time

import typer
from vethuq_core.branding import APP_NAME, APP_TAGLINE
from vethuq_core.errors import StartupError
from vethuq_core.index import Indexing
from vethuq_core.logs import Logs
from vethuq_core.storage import default_db_path

from vethuq_cli.console import error_console
from vethuq_cli.db import app as db_app
from vethuq_cli.filetypes import app as types_app
from vethuq_cli.index import app as index_app
from vethuq_cli.interactive import InteractiveMenu
from vethuq_cli.logs import LogsCommand
from vethuq_cli.ocr import app as ocr_app
from vethuq_cli.search import SearchHelp
from vethuq_cli.search import search as search_command
from vethuq_cli.search_engines import app as search_engines_app
from vethuq_cli.semantic import app as semantic_app
from vethuq_cli.settings import app as settings_app
from vethuq_cli.source import app as source_app
from vethuq_cli.stats import app as stats_app
from vethuq_cli.version import VersionCommand

_logger = Logs.get_logger("cli")

app = typer.Typer(help=f"{APP_NAME} — {APP_TAGLINE}")
app.add_typer(source_app, name="source")
app.add_typer(index_app, name="index")
if Indexing.has_service():  # the pip package ships without the background service
    from vethuq_cli.background import app as background_app

    app.add_typer(background_app, name="background-service")
app.add_typer(settings_app, name="settings")
app.add_typer(stats_app, name="stats")
app.add_typer(db_app, name="db")
app.add_typer(types_app, name="file-types")
app.add_typer(search_engines_app, name="search-engines")
app.add_typer(ocr_app, name="ocr")
app.add_typer(semantic_app, name="semantic")
app.command("search", help=SearchHelp.TEXT)(search_command)
app.command("logs", help=LogsCommand.HELP)(LogsCommand.run)


def _show_version(value: bool) -> None:
    if value:
        VersionCommand.show()
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_show_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Run a subcommand, or launch the interactive console when none is given."""
    Logs.setup("cli", default_db_path())
    _logger.info("Started: vethuq %s", Logs.loggable_command(sys.argv[1:]))
    if ctx.invoked_subcommand is None:
        InteractiveMenu.run()


class Cli:
    @staticmethod
    def run() -> None:
        """Console-script entry point: run `app`, reporting startup errors cleanly."""
        started = time.monotonic()
        code: int | str | None = 0
        try:
            app()
        except StartupError as exc:
            _logger.error("%s", exc)
            error_console.print(f"Error: {exc.message}", style="bold red")
            if exc.hint:
                error_console.print(f"What to do: {exc.hint}")
            code = exc.exit_code
            raise SystemExit(exc.exit_code) from None
        except SystemExit as exc:  # typer/click exit through SystemExit, even on success
            code = exc.code
            raise
        except BaseException:
            code = 1
            _logger.exception("Unhandled error")
            raise
        finally:
            _logger.info("Finished: exit code %s after %.2fs", code, time.monotonic() - started)


if __name__ == "__main__":
    Cli.run()
