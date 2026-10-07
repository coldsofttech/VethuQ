"""`vethuq ocr models ...` commands: the OCR models each language needs on disk."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from vethuq_core.formatting import Formatting
from vethuq_core.languages import Languages
from vethuq_core.ocr.catalog import OcrCatalog
from vethuq_core.ocr.models import ModelStatus, OcrModels
from vethuq_core.sorting import Sorting

from vethuq_cli.console import console, error_console
from vethuq_cli.sorting import SortOptions
from vethuq_cli.theme import Theme

app = typer.Typer(help="OCR commands.")
models_app = typer.Typer(help="Download, inspect and remove the OCR models languages need.")
app.add_typer(models_app, name="models")

LANG_HELP = (
    "Language id (e.g. 'te'); repeat or comma-separate for several, or 'all' for every enabled "
    "language."
)


class ModelsCommand:
    TITLE = "OCR models"

    @staticmethod
    def panel(content: Text | Table, border: str = Theme.PRIMARY) -> Panel:
        if isinstance(content, Text):
            content.no_wrap = False
            content.overflow = "fold"
        return Panel(
            content, title=Text(ModelsCommand.TITLE), title_align="left", border_style=border
        )

    @staticmethod
    def fail(message: str, hint: str | None = None) -> typer.Exit:
        error_console.print(message, style=Theme.ERROR)
        if hint:
            error_console.print(f"What to do: {hint}")
        return typer.Exit(code=1)

    @staticmethod
    def languages(values: list[str] | None, *, required: bool) -> list[str]:
        """The language ids `--lang` names (comma-separated and/or repeated; `all` is every
        enabled language). Without it: every enabled language, or - for a command that deletes -
        an error asking which."""
        enabled = Languages.enabled_ids()
        wanted = [part.strip() for v in values or [] for part in v.split(",") if part.strip()]
        if not wanted:
            if required:
                raise ModelsCommand.fail(
                    "Say which language: --lang <id> (or --lang all).",
                    f"Enabled languages: {', '.join(enabled)}.",
                )
            return enabled
        if "all" in wanted:
            return enabled
        for language_id in wanted:
            known = OcrCatalog.language(language_id)
            if known is None:
                raise ModelsCommand.fail(
                    f"Unknown language '{language_id}'.", f"Known: {', '.join(known_ids())}."
                )
            if language_id not in enabled:
                raise ModelsCommand.fail(
                    f"The {known.label} language is not installed or enabled.",
                    f"Install it with: {known.install_hint}",
                )
        return list(dict.fromkeys(wanted))

    @staticmethod
    def table(statuses: list[ModelStatus]) -> Table:
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("Model", "Used by", "Size", "Status"):
            table.add_column(column)
        for model in statuses:
            table.add_row(
                Text(model.name, style="bold"),
                Text("all languages" if model.shared else ", ".join(model.languages)),
                Text(Formatting.size(model.size_bytes) if model.present else "-"),
                Text("downloaded", style=Theme.OK)
                if model.present
                else Text("not downloaded", style=Theme.WARNING),
            )
        return table

    @staticmethod
    def confirm(prompt: str, force: bool) -> None:
        if force:
            return
        if not Confirm.ask(Text(prompt), console=console, default=False):
            console.print(ModelsCommand.panel(Text("Aborted."), "bright_black"))
            raise typer.Exit(code=0)

    @staticmethod
    def download(language_ids: list[str], *, force: bool) -> bool:
        """Download the models `language_ids` need, showing progress; True if all arrived."""
        labels = {}
        for model in OcrModels.status(language_ids):
            labels[model.name] = model.name
        with console.status("Downloading OCR models...", spinner_style=Theme.PRIMARY) as spinner:

            def progress(name: str, state: str) -> None:
                if state == "downloading":
                    spinner.update(f"Downloading {name}...")
                elif state == "ready":
                    console.print(Text.assemble(("  downloaded ", Theme.OK), (name, "white")))
                elif state == "failed":
                    console.print(Text.assemble(("  failed ", Theme.ERROR), (name, "white")))

            result = OcrModels.download(language_ids, force=force, on_progress=progress)
        for name, reason in result.failed.items():
            error_console.print(f"{name}: {reason}", style=Theme.ERROR)
        if result.failed:
            error_console.print(
                "What to do: check the internet connection and run the command again; "
                "models already downloaded are kept."
            )
            return False
        summary = (
            f"{len(result.downloaded)} downloaded, {len(result.already_present)} already there."
        )
        console.print(ModelsCommand.panel(Text(summary, style="white"), Theme.OK))
        return True


def known_ids() -> list[str]:
    return [lang.id for lang in OcrCatalog.languages()]


@models_app.command("status")
def status(
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    sort: SortOptions.ORDER = None,
    sort_by: SortOptions.MODELS = None,
) -> None:
    """Show which OCR models are downloaded, for every enabled language or the ones named."""
    language_ids = ModelsCommand.languages(lang, required=False)
    statuses = Sorting.models(OcrModels.status(language_ids), sort_by, sort)
    body = Table.grid(padding=(0, 0))
    body.add_row(ModelsCommand.table(statuses))
    body.add_row(Text(f"\nFolder: {OcrModels.cache_dir()}", style="bright_black"))
    console.print(ModelsCommand.panel(body))


@models_app.command("download")
def download(
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    force: bool = typer.Option(
        False, "--force", help="Download again even for models that are already there."
    ),
) -> None:
    """Download the models for every enabled language (or the ones named) that are missing.

    OCR also downloads a missing model the first time it needs it; this lets you do it ahead of
    time, for example before going offline.
    """
    language_ids = ModelsCommand.languages(lang, required=False)
    if not ModelsCommand.download(language_ids, force=force):
        raise typer.Exit(code=1)


@models_app.command("clear")
def clear(
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    include_shared: bool = typer.Option(
        False,
        "--include-shared",
        help="Also remove the models every language shares (text detection and orientation).",
    ),
    force: bool = typer.Option(False, "--force", help="Delete without asking for confirmation."),
) -> None:
    """Delete the downloaded models of a language.

    The models all languages share stay unless --include-shared is given, because the other
    languages still need them. A deleted model is downloaded again the next time it is needed.
    """
    language_ids = ModelsCommand.languages(lang, required=True)
    ModelsCommand.confirm(
        f"Delete the OCR models of {', '.join(language_ids)}"
        f"{' and the shared ones' if include_shared else ''}?",
        force,
    )
    result = OcrModels.clear(language_ids, include_shared=include_shared)
    lines = [f"Removed: {', '.join(result.removed) or 'nothing'}."]
    if result.kept_shared:
        lines.append(f"Kept (shared by every language): {', '.join(result.kept_shared)}.")
    console.print(ModelsCommand.panel(Text("\n".join(lines), style="white"), Theme.OK))


@models_app.command("reset")
def reset(
    lang: list[str] | None = typer.Option(None, "--lang", help=LANG_HELP),  # noqa: B008
    force: bool = typer.Option(False, "--force", help="Reset without asking for confirmation."),
) -> None:
    """Delete a language's models and download them again, to repair a damaged download.

    Needs the internet. If the download fails the models stay deleted, and OCR (or 'vethuq ocr
    models download') fetches them again later.
    """
    language_ids = ModelsCommand.languages(lang, required=True)
    ModelsCommand.confirm(
        f"Delete and download again the OCR models of {', '.join(language_ids)}?", force
    )
    OcrModels.clear(language_ids)
    if not ModelsCommand.download(language_ids, force=False):
        raise typer.Exit(code=1)


@models_app.command("clean")
def clean(
    force: bool = typer.Option(False, "--force", help="Delete without asking for confirmation."),
) -> None:
    """Remove OCR models nothing uses: those of languages that are not enabled, and leftovers
    of interrupted downloads.

    Models of enabled languages stay, and so does anything in the cache that is not a VethuQ
    model (it belongs to another program using PaddleX).
    """
    ModelsCommand.confirm("Delete the OCR models no enabled language uses?", force)
    result = OcrModels.clean(Languages.enabled_ids())
    lines = [
        f"Removed: {', '.join(result.removed) or 'nothing'}"
        + (f" ({Formatting.size(result.bytes_freed)} freed)." if result.removed else ".")
    ]
    if result.unmanaged:
        lines.append(f"Left alone (not VethuQ models): {', '.join(result.unmanaged)}.")
    console.print(ModelsCommand.panel(Text("\n".join(lines), style="white"), Theme.OK))
