"""`vethuq db ...` database maintenance commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.db.backup import Backup, BackupError, BackupInfo
from vethuq_core.db.integrity import IntegrityCheck
from vethuq_core.index.runner import IndexRunner
from vethuq_core.storage import default_db_path, open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Database maintenance commands.")
backup_app = typer.Typer(help="Create, list and delete compressed database backups.")
app.add_typer(backup_app, name="backup")


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
    def confirm(question: str, force: bool) -> None:
        if force:
            return
        if not Confirm.ask(question, console=console, default=False):
            console.print(Panel(Text("Aborted.", style="bright_black"), expand=True))
            raise typer.Exit(code=0)

    @staticmethod
    def panel(message: Text, title: str, style: str) -> None:
        console.print(Panel(message, title=title, title_align="left", border_style=style))

    @staticmethod
    def safety_note(safety: BackupInfo | None) -> Text:
        if safety is None:
            return Text("")
        return Text.assemble(
            ("\n\nThe previous database was saved as '", "white"),
            (safety.name, Theme.VALUE),
            ("' (restore it with 'vethuq db restore ", "white"),
            (safety.name, Theme.VALUE),
            ("').", "white"),
        )

    @staticmethod
    def size(num_bytes: int) -> str:
        if num_bytes < 1024:
            return f"{num_bytes} B"
        value = num_bytes / 1024
        for unit in ("KB", "MB"):
            if value < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"


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
    try:
        info = Backup.create(default_db_path(), name)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    DbCommands.panel(
        Text.assemble(
            ("Backup '", "white"),
            (info.name, Theme.VALUE),
            (f"' created ({DbCommands.size(info.size)}).", "white"),
        ),
        "Backup",
        Theme.OK,
    )


@backup_app.command("list")
def backup_list() -> None:
    """List the database backups, newest first."""
    infos = Backup.entries(default_db_path())
    if not infos:
        DbCommands.panel(Text("No backups yet.", style="white"), "Backups", Theme.PRIMARY)
        return
    table = Table(title="Backups", title_justify="left", expand=True)
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Created")
    table.add_column("Size", justify="right")
    for info in infos:
        table.add_row(
            info.name,
            info.kind,
            info.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            DbCommands.size(info.size),
        )
    console.print(table)


@backup_app.command("delete")
def backup_delete(
    name: str = typer.Argument(..., help="Name of the backup, as shown by 'backup list'."),
    force: bool = typer.Option(False, "--force", help="Delete without asking for confirmation."),
) -> None:
    """Delete one database backup."""
    DbCommands.confirm(f"Delete backup '{name}'?", force)
    try:
        Backup.delete(default_db_path(), name)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    DbCommands.panel(Text(f"Backup '{name}' deleted.", style="white"), "Backup", Theme.OK)


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
        f"Replace the current database with '{source}'? Changes made since that backup "
        "will be lost.",
        force,
    )
    try:
        safety = Backup.restore(db_path, source)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    message = Text.assemble(
        ("Database restored from '", "white"), (source, Theme.VALUE), ("'.", "white")
    )
    message.append_text(DbCommands.safety_note(safety))
    DbCommands.panel(message, "Restore", Theme.OK)


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
        "Clear ALL data - registered sources, the search index and settings? "
        "Your source files themselves are not touched.",
        force,
    )
    try:
        safety = Backup.reset(db_path)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    message = Text("The database was reset.", style="white")
    message.append_text(DbCommands.safety_note(safety))
    DbCommands.panel(message, "Reset", Theme.OK)


@app.command("repair")
def repair() -> None:
    """Rebuild the database's indexes (REINDEX) and check it again.

    Fixes index-only corruption. If the check still fails, restore a backup
    ('vethuq db backup list', 'vethuq db restore') or reset the database.
    """
    db_path = default_db_path()
    DbCommands.require_idle(db_path)
    try:
        result, safety = Backup.repair(db_path)
    except BackupError as exc:
        raise DbCommands.fail(str(exc)) from exc
    if result.ok:
        message = Text("Database repaired: the integrity check now passes.", style="white")
        message.append_text(DbCommands.safety_note(safety))
        DbCommands.panel(message, "Repair", Theme.OK)
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
