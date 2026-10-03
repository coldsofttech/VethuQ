"""`vethuq db ...` database maintenance commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.db.backup import Backup, BackupError, BackupInfo
from vethuq_core.db.integrity import IntegrityCheck
from vethuq_core.index.runner import IndexRunner
from vethuq_core.storage import default_db_path, open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.index.panel import IndexPanel
from vethuq_cli.theme import Theme

app = typer.Typer(help="Database maintenance commands.")
backup_app = typer.Typer(help="Create, list and delete compressed database backups.")
app.add_typer(backup_app, name="backup")


class DbPanel:
    @staticmethod
    def build(message: str | Text | Table, border_style: str, title: str = "Database") -> Panel:
        """A full-width panel (titled "Database" by default): `message` (white unless already
        styled), left-aligned title, coloured border."""
        content: RenderableType
        if isinstance(message, Table):
            content = message
        else:
            content = Text(message, style="white") if isinstance(message, str) else message
            # The shared console is soft-wrapping, which would crop long lines in a panel.
            content.no_wrap = False
            content.overflow = "fold"
        return Panel(
            content,
            title=Text(title),
            title_align="left",
            border_style=border_style,
            expand=True,
        )

    @staticmethod
    def size(num_bytes: int) -> str:
        value = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{num_bytes} B"

    @staticmethod
    def safety_note(safety: BackupInfo | None) -> Text:
        """Where the database that was just replaced went, and how to get it back."""
        if safety is None:
            return Text()
        return Text.assemble(
            ("\n\nThe previous database was saved as ", "white"),
            (safety.name, Theme.VALUE),
            (". Undo with 'vethuq db restore ", "white"),
            (safety.name, Theme.VALUE),
            ("'.", "white"),
        )


class DbCommands:
    """Shared helpers for the backup / restore / reset / repair commands."""

    @staticmethod
    def fail(message: str) -> typer.Exit:
        error_console.print(message, style=Theme.ERROR)
        return typer.Exit(code=1)

    @staticmethod
    def require_idle(db_path: Path) -> None:
        """Refuse to touch the database files while an index run could be writing to them."""
        if IndexRunner.is_running(db_path)[0]:
            raise DbCommands.fail(
                "An index run is in progress. Stop it first with 'vethuq index stop'."
            )

    @staticmethod
    def confirm(prompt: Text, title: str, force: bool) -> None:
        """Ask first unless `force`; "Aborted." (exit 0) if the answer is no."""
        if force:
            return
        if not Confirm.ask(prompt, console=console, default=False):
            console.print(DbPanel.build("Aborted.", "bright_black", title))
            raise typer.Exit(code=0)


@app.command("integrity-check")
def integrity_check() -> None:
    """Run `PRAGMA integrity_check` now and print the result.

    Also logged via the standard `logging` module (info on success, error
    with the specific corruption messages on failure). See 'vethuq settings
    db integrity-check' to control whether this also runs automatically
    when the database is opened.
    """
    storage = open_storage()
    try:
        result = IntegrityCheck.run(storage)
    finally:
        storage.close()

    if result.ok:
        console.print(
            Panel(
                Text("Database integrity check passed.", style="white"),
                title="Integrity Check",
                title_align="left",
                border_style=Theme.OK,
                expand=True,
            )
        )
        return

    error_console.print("Database integrity check FAILED:", style=Theme.ERROR)
    for message in result.errors:
        error_console.print(f"  {message}", style=Theme.ERROR)
    raise typer.Exit(code=1)


@backup_app.command("create")
def backup_create(
    name: str | None = typer.Argument(
        None, help="Name for the snapshot (letters, digits, '.', '_', '-'). Default: timestamped."
    ),
) -> None:
    """Take a compressed backup of the database now.

    Named snapshots are never deleted automatically. Automatic backups are pruned
    after 'vethuq settings db backup retention' days.
    """
    open_storage().close()  # a fresh install has no database file until something opens it
    try:
        info = Backup.create(default_db_path(), name)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    console.print(
        DbPanel.build(
            Text.assemble(
                ("Backup created: ", Theme.OK),
                (info.name, "white"),
                (f" ({DbPanel.size(info.size)})", "bright_black"),
            ),
            Theme.OK,
            "Backups",
        )
    )


@backup_app.command("list")
def backup_list() -> None:
    """List the database backups, newest first."""
    infos = Backup.entries(default_db_path())
    if not infos:
        console.print(DbPanel.build("No backups yet.", "bright_black", "Backups"))
        return

    table = Table(box=box.SIMPLE, header_style=f"bold {Theme.PRIMARY}", border_style=Theme.PRIMARY)
    table.add_column("Name", no_wrap=False, overflow="fold")
    table.add_column("Kind", style=Theme.LABEL)
    table.add_column("Created")
    table.add_column("Size", justify="right", style="bright_black")
    for info in infos:
        table.add_row(
            info.name,
            info.kind,
            IndexPanel.friendly_time(info.created_at.isoformat()),
            DbPanel.size(info.size),
        )
    console.print(DbPanel.build(table, Theme.PRIMARY, "Backups"))


@backup_app.command("delete")
def backup_delete(
    name: str = typer.Argument(..., help="Name of the backup, as shown by 'backup list'."),
    force: bool = typer.Option(False, "--force", help="Delete without asking for confirmation."),
) -> None:
    """Delete one database backup."""
    DbCommands.confirm(Text.assemble("Delete backup ", (name, Theme.VALUE), "?"), "Backups", force)
    try:
        Backup.delete(default_db_path(), name)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    console.print(
        DbPanel.build(
            Text.assemble(("Backup deleted: ", Theme.OK), (name, "white")), Theme.OK, "Backups"
        )
    )


@app.command("restore")
def restore(
    source: str = typer.Argument(
        ..., help="A backup name (see 'backup list') or the path of a backup file (.db.gz)."
    ),
    force: bool = typer.Option(False, "--force", help="Restore without asking for confirmation."),
) -> None:
    """Replace the database with a backup.

    The backup is verified first, and the current database is saved as a
    'safety-...' backup so the restore can be undone.
    """
    db_path = default_db_path()
    DbCommands.require_idle(db_path)
    DbCommands.confirm(
        Text.assemble(
            "Replace the current database with ",
            (source, Theme.VALUE),
            "? Changes made since that backup will be lost.",
        ),
        "Restore",
        force,
    )
    try:
        safety = Backup.restore(db_path, source)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    message = Text.assemble(("Database restored from ", Theme.OK), (source, "white"))
    message.append_text(DbPanel.safety_note(safety))
    console.print(DbPanel.build(message, Theme.OK, "Restore"))


@app.command("reset")
def reset(
    force: bool = typer.Option(False, "--force", help="Reset without asking for confirmation."),
) -> None:
    """Delete the database and all the data in it (sources, index, settings).

    The current database is saved as a 'safety-...' backup first, and a fresh
    empty one is created the next time VethuQ runs.
    """
    db_path = default_db_path()
    DbCommands.require_idle(db_path)
    DbCommands.confirm(
        Text(
            "Clear ALL data - registered sources, the search index and settings? "
            "Your source files themselves are not touched."
        ),
        "Reset",
        force,
    )
    try:
        safety = Backup.reset(db_path)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    message = Text("Database reset: all data cleared.", style=Theme.OK)
    message.append_text(DbPanel.safety_note(safety))
    console.print(DbPanel.build(message, Theme.OK, "Reset"))


@app.command("repair")
def repair(
    force: bool = typer.Option(False, "--force", help="Repair without asking for confirmation."),
) -> None:
    """Rebuild the database's indexes (REINDEX) and check it again.

    Fixes index-only corruption. If the check still fails, restore a backup
    ('vethuq db backup list', 'vethuq db restore') or reset the database.
    """
    db_path = default_db_path()
    DbCommands.require_idle(db_path)
    DbCommands.confirm(
        Text(
            "Rebuild the database's indexes and check it again? "
            "The current database is backed up first."
        ),
        "Repair",
        force,
    )
    try:
        result, safety = Backup.repair(db_path)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    if result.ok:
        message = Text("Database repaired: the integrity check now passes.", style=Theme.OK)
        message.append_text(DbPanel.safety_note(safety))
        console.print(DbPanel.build(message, Theme.OK, "Repair"))
        return
    error_console.print("The database could not be repaired:", style=Theme.ERROR)
    for line in result.errors:
        error_console.print(f"  {line}", style=Theme.ERROR)
    error_console.print(
        "Restore a backup with 'vethuq db restore <name>' (see 'vethuq db backup list'), "
        "or clear everything with 'vethuq db reset'.",
        style=Theme.ERROR,
    )
    raise typer.Exit(code=1)
