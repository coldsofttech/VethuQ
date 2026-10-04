"""The version panel shown by `vethuq --version` and the interactive menu."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from vethuq_core.logs import Logs
from vethuq_core.settings.filetypes import FileTypeSettings
from vethuq_core.storage import open_storage
from vethuq_core.version import VersionInfo

from vethuq_cli.console import console

_logger = Logs.get_logger("cli")


class VersionCommand:
    @staticmethod
    def _record_installed_extras() -> None:
        """Keep the database's record of installed `type-*` and `search-*` packages current.
        Showing the version must work even when the database can't be opened, so failures are
        only logged."""
        try:
            storage = open_storage()
            try:
                FileTypeSettings.record_installed(storage)
                FileTypeSettings.record_installed_engines(storage)
            finally:
                storage.close()
        except Exception:  # noqa: BLE001 - never block the version on the database
            _logger.warning(
                "Could not record installed file types and search engines", exc_info=True
            )

    @staticmethod
    def show() -> None:
        VersionCommand._record_installed_extras()
        table = Table.grid(padding=(0, 2))
        for label, text in VersionInfo.rows():
            table.add_row(Text(label, style="bold"), Text(text, style="white"))
        console.print(
            Panel(
                table, title=Text("Version"), title_align="left", border_style="cyan", expand=True
            )
        )
