"""VethuQ CLI entry point."""

from __future__ import annotations

import sys
import time

import typer
from vethuq_core.branding import APP_NAME, APP_TAGLINE
from vethuq_core.logs import Logs
from vethuq_core.storage import SchemaVersionError, default_db_path

from vethuq_cli.console import error_console
from vethuq_cli.db import app as db_app
from vethuq_cli.index import app as index_app
from vethuq_cli.interactive import InteractiveMenu
from vethuq_cli.logs import LogsCommand
from vethuq_cli.search import search as search_command
from vethuq_cli.settings import app as settings_app
from vethuq_cli.source import app as source_app
from vethuq_cli.stats import app as stats_app

_logger = Logs.get_logger("cli")

app = typer.Typer(help=f"{APP_NAME} — {APP_TAGLINE}")
app.add_typer(source_app, name="source")
app.add_typer(index_app, name="index")
app.add_typer(settings_app, name="settings")
app.add_typer(stats_app, name="stats")
app.add_typer(db_app, name="db")
app.command("search")(search_command)
app.command("logs")(LogsCommand.run)


def _loggable_command(argv: list[str]) -> str:
    """The invocation for the log, without what a user searched for (it can be sensitive)."""
    if not argv:
        return "(interactive)"
    if argv[0] == "search":
        return "search <query omitted>"
    return " ".join(argv)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Run a subcommand, or launch the interactive console when none is given."""
    Logs.setup("cli", default_db_path())
    _logger.info("Started: vethuq %s", _loggable_command(sys.argv[1:]))
    if ctx.invoked_subcommand is None:
        InteractiveMenu.run()


class Cli:
    @staticmethod
    def run() -> None:
        """Console-script entry point: run `app`, reporting an unsupported database cleanly."""
        started = time.monotonic()
        code: int | str | None = 0
        try:
            app()
        except SchemaVersionError as exc:
            _logger.error("%s", exc)
            error_console.print(f"Error: {exc}", style="bold red")
            code = 1
            raise SystemExit(1) from None
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
