"""`vethuq semantic ...` commands: the model and the index behind the `semantic` search engine."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.formatting import Formatting
from vethuq_core.search.engines.catalog import SearchEngineCatalog
from vethuq_core.semantic import (
    Embedders,
    SemanticIndex,
    SemanticModel,
    SemanticModelError,
)
from vethuq_core.storage import open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.theme import Theme

app = typer.Typer(help="Manage the model and index behind `semantic` search.")


class SemanticCommand:
    TITLE = "Semantic search"

    @staticmethod
    def panel(content: Text | Table, border: str = Theme.PRIMARY) -> Panel:
        if isinstance(content, Text):
            content.no_wrap = False
            content.overflow = "fold"
        return Panel(
            content, title=Text(SemanticCommand.TITLE), title_align="left", border_style=border
        )

    @staticmethod
    def fail(message: str, hint: str | None = None) -> typer.Exit:
        error_console.print(message, style=Theme.ERROR)
        if hint:
            error_console.print(f"What to do: {hint}")
        return typer.Exit(code=1)

    @staticmethod
    def require_engine() -> None:
        """Stop with the install hint unless the `semantic` engine is installed and enabled."""
        info = SearchEngineCatalog.get("semantic")
        reason = SearchEngineCatalog.unavailable_reason(info) if info is not None else None
        if reason is not None:
            raise SemanticCommand.fail(reason)

    @staticmethod
    def confirm(prompt: str, force: bool) -> None:
        if force:
            return
        if not Confirm.ask(Text(prompt), console=console, default=False):
            console.print(SemanticCommand.panel(Text("Aborted."), "bright_black"))
            raise typer.Exit(code=0)

    @staticmethod
    def download_model(*, force: bool) -> None:
        """Download the model (again, with `force`), showing what is being fetched."""
        if force:
            SemanticModel.remove()
        elif SemanticModel.is_downloaded():
            console.print(SemanticCommand.panel(Text("The model is already downloaded.")))
            return
        with console.status("Downloading the model...", spinner_style=Theme.PRIMARY) as spinner:
            try:
                SemanticModel.download(spinner.update)
            except SemanticModelError as exc:
                raise SemanticCommand.fail(
                    str(exc), "check the internet connection and run the command again."
                ) from exc
        console.print(
            SemanticCommand.panel(
                Text(f"Downloaded {SemanticModel.MODEL_ID}.", style="white"), Theme.OK
            )
        )


@app.command("status")
def status() -> None:
    """Show whether the semantic model is downloaded and how much of your text is embedded."""
    model = SemanticModel.status()
    storage = open_storage()
    try:
        index = SemanticIndex.status(storage, SemanticModel.MODEL_ID)
    finally:
        storage.close()
    table = Table.grid(padding=(0, 2))
    table.add_column(style=Theme.LABEL, no_wrap=True)
    table.add_column()
    table.add_row("Model", Text(model.model))
    table.add_row(
        "Downloaded",
        Text(f"yes ({Formatting.size(model.size_bytes)})", style=Theme.OK)
        if model.present
        else Text("no - downloads the first time it is used", style=Theme.WARNING),
    )
    table.add_row(
        "Folder",
        Text(str(model.path), style="bright_black", no_wrap=False, overflow="fold"),
    )
    table.add_row(
        "Pages embedded",
        Text(
            f"{index.embedded} of {index.pages}"
            + (f" ({index.pending} to go)" if index.pending else ""),
            style="white" if index.pending else Theme.OK,
        ),
    )
    table.add_row("Passages", Text(str(index.chunks)))
    if index.stale:
        table.add_row(
            "Out of date",
            Text(
                f"{index.stale} pages were embedded another way and are embedded again "
                "by the next search or `vethuq semantic index`",
                style=Theme.WARNING,
            ),
        )
    table.add_row("Embedding version", Text(index.version))
    if index.path is not None:
        table.add_row(
            "Store",
            Text(
                f"{index.path} ({Formatting.size(index.size_bytes)})",
                style="bright_black",
                no_wrap=False,
                overflow="fold",
            ),
        )
    console.print(SemanticCommand.panel(table))


@app.command("download")
def download(
    force: bool = typer.Option(
        False, "--force", help="Download again even if the model is already there."
    ),
) -> None:
    """Download the semantic model (multilingual-e5-small) if it is missing.

    A semantic search also downloads it the first time it needs it; this lets you do it ahead
    of time, for example before going offline.
    """
    SemanticCommand.require_engine()
    SemanticCommand.download_model(force=force)


@app.command("index")
def index(
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Forget every embedding first and embed everything again."
    ),
) -> None:
    """Embed the pages that have no embedding yet, so the next semantic search starts at once.

    Downloads the model first if needed. Pages are embedded in batches and each batch is kept,
    so stopping early loses nothing; run it again to carry on. A semantic search embeds whatever
    is missing itself, so this is only for doing the work ahead of time.
    """
    SemanticCommand.require_engine()
    storage = open_storage()
    try:
        try:
            with console.status("Loading the model...", spinner_style=Theme.PRIMARY) as spinner:
                embedder = Embedders.get(spinner.update)
        except SemanticModelError as exc:
            raise SemanticCommand.fail(
                str(exc), "check the internet connection and run the command again."
            ) from exc
        if rebuild:
            SemanticIndex.clear(storage, embedder.model)
        pending = SemanticIndex.status(storage, embedder.model).pending
        if not pending:
            console.print(
                SemanticCommand.panel(Text("Every page is already embedded.", style=Theme.OK))
            )
            return
        with Progress(
            TextColumn("Embedding pages"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("embed", total=pending)
            result = SemanticIndex.sync(
                storage,
                embedder,
                on_progress=lambda done, total: progress.update(task, completed=done, total=total),
            )
        console.print(
            SemanticCommand.panel(
                Text(
                    f"Embedded {result.pages} pages ({result.chunks} passages).",
                    style="white",
                ),
                Theme.OK,
            )
        )
    finally:
        storage.close()


@app.command("clear")
def clear(
    model: bool = typer.Option(
        False, "--model", help="Also delete the downloaded model, not just the embeddings."
    ),
    force: bool = typer.Option(False, "--force", help="Delete without asking for confirmation."),
) -> None:
    """Forget the embeddings of every page (and, with --model, delete the model too).

    Both come back on their own: the next semantic search embeds the pages again, downloading
    the model first if it was deleted.
    """
    SemanticCommand.confirm(
        "Delete every embedding" + (" and the downloaded model?" if model else "?"), force
    )
    storage = open_storage()
    try:
        pages = SemanticIndex.clear(storage)
    finally:
        storage.close()
    removed = SemanticModel.remove() if model else False
    lines = [f"Forgot the embeddings of {pages} pages."]
    if model:
        lines.append("Deleted the model." if removed else "The model was not downloaded.")
    console.print(SemanticCommand.panel(Text("\n".join(lines), style="white"), Theme.OK))
