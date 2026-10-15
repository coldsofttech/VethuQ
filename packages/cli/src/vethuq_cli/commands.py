"""The built-in commands, written against the public `vethuq` API."""

from __future__ import annotations

import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.live import Live

from vethuq.enums import SortOrder, SourceSortBy
from vethuq_cli.console import Theme, console
from vethuq_cli.display import index_panel, search_panel, stats_panel
from vethuq_cli.export import exportable
from vethuq_cli.output import dump, facts, plain, say, table
from vethuq_cli.state import State

Languages = Annotated[
    list[str] | None, typer.Option("--language", "-l", help="A language id; repeat for several.")
]


class FileSortBy(StrEnum):
    NAME = "name"
    SIZE = "size"
    STATUS = "status"


def _file_key(f, sort_by: FileSortBy):
    if sort_by is FileSortBy.SIZE:
        return f.size_bytes or 0
    if sort_by is FileSortBy.STATUS:
        return str((plain(f.index) or {}).get("status", ""))
    return f.name


def client():
    return State.client()


def show_version() -> None:
    facts(client().version, title="VethuQ")


# ----- source ---------------------------------------------------------------------------------

source_app = typer.Typer(help="Folders and files VethuQ reads.", no_args_is_help=True)


@source_app.command("add")
def source_add(path: Path, language: Languages = None) -> None:
    """Add a folder or file as a source."""
    found = client().sources.create(path, languages=language or None)
    say(f"Added source {found.id}: {found.path}", style=Theme.OK, data=found)


@source_app.command("list")
@exportable("Sources", "sources", facets=("source_type", "status"))
def source_list(
    removed: bool = typer.Option(False, "--removed", help="Include removed."),
    sort_by: Annotated[
        SourceSortBy, typer.Option("--sort-by", help="Field to sort by.")
    ] = SourceSortBy.ID,
    order: Annotated[SortOrder, typer.Option("--order", help="asc or desc.")] = SortOrder.ASC,
) -> None:
    """List the sources."""
    table(
        client().sources.list(include_removed=removed, sort_by=sort_by, order=order),
        ["id", "path", "source_type", "status", "languages", "files_total", "files_processed"],
        empty="No sources. Add one with: vethuq source add PATH",
    )


@source_app.command("files")
@exportable("Files", "files", facets=("status", "file_type"))
def source_files(
    source: str,
    detailed: bool = typer.Option(False, "--detailed"),
    sort_by: Annotated[
        FileSortBy, typer.Option("--sort-by", help="Field to sort by.")
    ] = FileSortBy.NAME,
    order: Annotated[SortOrder, typer.Option("--order", help="asc or desc.")] = SortOrder.ASC,
) -> None:
    """List the files of a source with their index state."""
    rows = client().sources.list_files(_ident(source), detailed=detailed)
    rows = sorted(rows, key=lambda f: _file_key(f, sort_by), reverse=order is SortOrder.DESC)
    table(
        [{"name": f.name, "size_bytes": f.size_bytes, **(plain(f.index) or {})} for f in rows],
        ["name", "size_bytes", "status", "pages", "confidence", "languages", "file_type"],
    )


@source_app.command("remove")
def source_remove(source: str) -> None:
    """Remove a source (it is purged after the retention period)."""
    found = client().sources.remove(_ident(source))
    say(f"Removed source {found.id}: {found.path}", style=Theme.OK, data=found)


@source_app.command("purge")
def source_purge(source: str) -> None:
    """Delete a removed source and everything read from it, now."""
    result = client().sources.purge(_ident(source))
    say(f"Purged source {result.id}: {result.path}", style=Theme.OK, data=result)


@source_app.command("set-languages")
def source_set_languages(source: str, languages: list[str]) -> None:
    """Set the languages a source is read in (give none to use the defaults)."""
    found = client().sources.set_languages(_ident(source), languages or None)
    say(f"Source {found.id} is read in: {', '.join(found.languages)}", data=found)


@source_app.command("export")
def source_export(
    source: str,
    output: Path,
    format: str = typer.Option(None, "--format", help="json or html."),  # noqa: A002
) -> None:
    """Export a source's files and index details."""
    found = client().sources.get(_ident(source))
    path = client().sources.export([found], output, format)
    say(f"Wrote {path}", style=Theme.OK, data={"path": str(path)})


def _ident(value: str) -> int | str:
    return int(value) if value.isdigit() else value


# ----- index ----------------------------------------------------------------------------------

index_app = typer.Typer(help="Read the files of the sources.", no_args_is_help=True)
Workers = Annotated[str, typer.Option("--workers", help="auto, or 0 to 8.")]
Tier = Annotated[str, typer.Option("--tier", help="local, github, hybrid ...")]
Wait = Annotated[bool, typer.Option("--wait/--no-wait", help="Wait for remote jobs.")]
Timeout = Annotated[float, typer.Option("--timeout", help="Minutes to wait for remote jobs.")]
OneOff = Annotated[
    bool, typer.Option("--one-off", help="Run it here, even if a background service is running.")
]


def _workers(value: str | None) -> int | str | None:
    return None if value is None else int(value) if value.isdigit() else value


def _queued(mode: str, target, one_off: bool, workers, tier, wait, timeout, language) -> bool:
    """With a background service running for this data folder, ask it to do the work and say so
    (True); otherwise, or with `--one-off`, the caller runs it itself (False)."""
    if one_off or not client().index.queue.service_running():
        return False
    job = client().index.queue.submit(
        target,
        mode=mode,
        workers=_workers(workers),
        tier=tier,
        wait=wait,
        timeout=timeout,
        languages=language or None,
    )
    say(
        f"Queued request {job.id} for the background service. "
        "Follow it with: vethuq index queue show " + str(job.id),
        style=Theme.OK,
        data=job,
    )
    return True


def _run_report(run) -> None:
    facts(
        run,
        title=f"Index run {run.id}: {plain(run.status)}",
        skip=("eta",) if State.json else (),
    )


@index_app.command("run")
def index_run(
    target: str = typer.Argument(None, help="A source id or path; every source when omitted."),
    workers: Workers = None,
    tier: Tier = None,
    wait: Wait = None,
    timeout: Timeout = None,
    language: Languages = None,
    one_off: OneOff = False,
) -> None:
    """Index new, modified and failed files."""
    if _queued(
        "run", _ident(target) if target else None, one_off, workers, tier, wait, timeout, language
    ):
        return
    _run_report(
        client().index.run(
            _ident(target) if target else None,
            workers=_workers(workers),
            tier=tier,
            wait=wait,
            timeout=timeout,
            languages=language or None,
        )
    )


@index_app.command("restart")
def index_restart(
    target: str = typer.Argument(None),
    workers: Workers = None,
    tier: Tier = None,
    wait: Wait = None,
    timeout: Timeout = None,
    language: Languages = None,
    one_off: OneOff = False,
) -> None:
    """Index only the files that failed."""
    if _queued(
        "restart",
        _ident(target) if target else None,
        one_off,
        workers,
        tier,
        wait,
        timeout,
        language,
    ):
        return
    _run_report(
        client().index.restart(
            _ident(target) if target else None,
            workers=_workers(workers),
            tier=tier,
            wait=wait,
            timeout=timeout,
            languages=language or None,
        )
    )


reindex_app = typer.Typer(help="Read files again (it costs credits again).", no_args_is_help=True)
index_app.add_typer(reindex_app, name="reindex")


@reindex_app.command("source")
def reindex_source(
    source: str,
    workers: Workers = None,
    tier: Tier = None,
    language: Languages = None,
    one_off: OneOff = False,
) -> None:
    """Read every file of a source again."""
    if _queued("reindex", _ident(source), one_off, workers, tier, None, None, language):
        return
    _run_report(
        client().index.reindex(
            _ident(source), workers=_workers(workers), tier=tier, languages=language or None
        )
    )


@reindex_app.command("file")
def reindex_file(
    file: str,
    workers: Workers = None,
    tier: Tier = None,
    language: Languages = None,
    one_off: OneOff = False,
) -> None:
    """Read one file again (by path or file id)."""
    if _queued("file", _ident(file), one_off, workers, tier, None, None, language):
        return
    _run_report(
        client().index.reindex_file(
            _ident(file), workers=_workers(workers), tier=tier, languages=language or None
        )
    )


@index_app.command("submit")
def index_submit(
    target: str = typer.Argument(None, help="A source id or path, or a file; all when omitted."),
    mode: str = typer.Option("run", "--mode", help="run, restart, reindex or file."),
    workers: Workers = None,
    tier: Tier = None,
    language: Languages = None,
) -> None:
    """Queue indexing for a background worker, whether or not one is running yet."""
    job = client().index.queue.submit(
        _ident(target) if target else None,
        mode=mode,
        workers=_workers(workers),
        tier=tier,
        languages=language or None,
    )
    say(f"Queued request {job.id}.", style=Theme.OK, data=job)


queue_app = typer.Typer(help="Requests waiting for a background worker.", no_args_is_help=True)
index_app.add_typer(queue_app, name="queue")
JOB_COLUMNS = ["id", "mode", "target", "status", "run_id", "requested_at", "error"]


@queue_app.command("list")
@exportable("Index requests", "requests", facets=("mode", "status"))
def queue_list(
    status: str = typer.Option(None, "--status", help="queued, running, completed ..."),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """The requests, newest first."""
    table(
        client().index.queue.list(status, limit),
        JOB_COLUMNS,
        empty="No index requests.",
    )


@queue_app.command("show")
def queue_show(job: int) -> None:
    """One request."""
    facts(client().index.queue.get(job))


@queue_app.command("cancel")
def queue_cancel(job: int) -> None:
    """Take a waiting request out."""
    say(f"Cancelled request {client().index.queue.cancel(job).id}.", style=Theme.OK)


@index_app.command("status")
def index_status(
    live: bool = typer.Option(False, "--live", help="Keep showing until the run is over."),
    wait: bool = typer.Option(False, "--wait", help="Wait until it is over, then show."),
) -> None:
    """Where the latest run is, and how long it has left."""
    status = client().index.status(wait=wait)
    if live and status is not None and not status.finished and not State.json:
        with Live(
            index_panel(status, animated=True), console=console, refresh_per_second=4
        ) as view:
            while not status.finished:
                time.sleep(2.0)
                status = client().index.status() or status
                view.update(index_panel(status, animated=True))
        return
    if status is None:
        say("No index run yet.", style=Theme.DIM, data={"run": None})
        return
    if State.json:
        dump(status)
        return
    console.print(index_panel(status))


@index_app.command("pause")
def index_pause() -> None:
    """Pause the run that is going (it may be in another process)."""
    client().index.pause()
    say("Pause requested.", style=Theme.OK)


@index_app.command("resume")
def index_resume() -> None:
    """Resume a paused run."""
    client().index.resume()
    say("Resume requested.", style=Theme.OK)


@index_app.command("stop")
def index_stop(wait: bool = typer.Option(True, "--wait/--no-wait")) -> None:
    """Stop the run that is going; files keep the pages they have."""
    client().index.stop(wait=wait)
    say("Stop requested.", style=Theme.OK)


@index_app.command("clear-stale")
def index_clear_stale() -> None:
    """Clear runs left behind by a process that ended."""
    count = client().index.clear_stale()
    say(f"Cleared {count} left-behind run(s).", data={"cleared": count})


@index_app.command("history")
@exportable("Index history", "runs", facets=("status",))
def index_history(limit: int = typer.Option(20, "--limit")) -> None:
    """Past runs, newest first."""
    table(
        client().index.history(limit=limit),
        [
            "id",
            "mode",
            "status",
            "files_processed",
            "files_failed",
            "pages_processed",
            "started_at",
        ],
        empty="No index runs yet.",
    )


@index_app.command("jobs")
@exportable("Remote batches", "jobs", facets=("status",))
def index_jobs(limit: int = typer.Option(20, "--limit")) -> None:
    """Batches sent to a remote tier."""
    table(
        client().index.jobs(limit=limit),
        ["id", "run_id", "tier", "status", "images", "credits", "submitted_at"],
        empty="No remote jobs.",
    )


@index_app.command("collect")
def index_collect(
    wait: bool = typer.Option(False, "--wait"), timeout: float = typer.Option(None, "--timeout")
) -> None:
    """Collect remote jobs that have finished."""
    table(
        client().index.collect(wait=wait, timeout=timeout),
        ["id", "run_id", "tier", "status", "images", "credits"],
        empty="No remote jobs.",
    )


# ----- search ---------------------------------------------------------------------------------


def search_command(
    query: str,
    engine: str = typer.Option(None, "--engine", "-e", help="An engine, all or hybrid."),
    normalize: list[str] = typer.Option(None, "--normalize", "-n", help="normalizer=level"),  # noqa: B008
    option: list[str] = typer.Option(None, "--option", "-o", help="engine.option=value"),  # noqa: B008
    language: Languages = None,
    file_type: list[str] = typer.Option(None, "--file-type", "-t", help="Only files of this type."),  # noqa: B008
    source: list[int] = typer.Option(None, "--source", "-s", help="Only this source (its id)."),  # noqa: B008
    case_sensitive: bool = typer.Option(None, "--case-sensitive/--ignore-case"),
    context: int = typer.Option(None, "--context", help="Characters of context."),
    combine: str = typer.Option(None, "--combine", help="The keyword engine of hybrid."),
    limit: int = typer.Option(20, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    export: Path = typer.Option(None, "--export", help="Write the results to a file."),  # noqa: B008
    format: str = typer.Option(  # noqa: A002
        None, "--format", help="json or html (with --export; default: the saved export format)."
    ),
) -> None:
    """Search the indexed pages."""
    if format and not export:
        raise typer.BadParameter("--format needs --export.", param_hint="--format")
    result = client().search.run(
        query,
        engine=engine,
        normalize=",".join(normalize) if normalize else None,
        case_sensitive=case_sensitive,
        context_chars=context,
        languages=language or None,
        file_types=file_type or None,
        sources=source or None,
        options=",".join(option) if option else None,
        combine=combine,
        limit=limit,
        offset=offset,
    )
    if export:
        path = client().search.export(result, export, format)
        say(f"Wrote {path}", style=Theme.OK, data={"path": str(path)})
        return
    if State.json:
        dump(result)
        return
    console.print(search_panel(result))
    if result.index_rebuilt:
        console.print("The search index was rebuilt first.", style=Theme.DIM)
    if result.pending:
        console.print("Some pages are still being indexed.", style=Theme.WARN)
    if result.total > offset + len(result.matches):
        console.print(f"… more: use --offset {offset + limit}", style=Theme.DIM)


engines_app = typer.Typer(help="Search engines and normalizers.", no_args_is_help=True)


@engines_app.command("list")
@exportable("Search engines", "engines")
def engines_list() -> None:
    """The installed search engines."""
    table(
        client().search.engines(),
        ["id", "label", "available", "in_all", "approximate", "options", "reason"],
    )


@engines_app.command("normalizers")
@exportable("Normalizers", "normalizers")
def engines_normalizers() -> None:
    """The installed normalizers and their levels."""
    table(client().search.normalizers(), ["id", "levels", "identity", "setting"])


search_index_app = typer.Typer(help="The search index.", no_args_is_help=True)


@search_index_app.command("status")
def search_index_status() -> None:
    """How the search index stands."""
    facts(client().search.status())


@search_index_app.command("rebuild")
def search_index_rebuild() -> None:
    """Build the search index again from the stored page text."""
    result = client().search.rebuild()
    if not result.ok:
        raise SystemExit(f"Rebuild failed: {result.error}")
    say(f"Rebuilt: {result.pages} pages in {result.seconds:.1f}s", style=Theme.OK, data=result)


# ----- the rest -------------------------------------------------------------------------------

types_app = typer.Typer(help="The file types VethuQ can read.", no_args_is_help=True)


@types_app.command("list")
@exportable("File types", "file_types")
def types_list() -> None:
    """File types, with whether each is available."""
    table(
        client().file_types.list_all(),
        ["id", "label", "extensions", "available", "enabled", "reason"],
    )


languages_app = typer.Typer(help="Languages for reading documents.", no_args_is_help=True)


@languages_app.command("list")
@exportable("Languages", "languages")
def languages_list() -> None:
    """Every language, with whether it is available and enabled."""
    table(
        client().languages.list_all(),
        ["id", "label", "native_label", "default", "available", "enabled", "reason"],
    )


@languages_app.command("enable")
def languages_enable(language: str) -> None:
    """Switch a language on."""
    say(f"Enabled {client().languages.enable(language).id}", style=Theme.OK)


@languages_app.command("disable")
def languages_disable(language: str) -> None:
    """Switch a language off."""
    say(f"Disabled {client().languages.disable(language).id}", style=Theme.OK)


tiers_app = typer.Typer(
    help="Where pages are read: here, or on a remote tier.", no_args_is_help=True
)


@tiers_app.command("list")
@exportable("Tiers", "tiers")
def tiers_list() -> None:
    """The processing tiers."""
    table(client().tiers.list(), ["id", "label", "wallet", "available", "selected", "reason"])


@tiers_app.command("use")
def tiers_use(tier: str) -> None:
    """Make a tier the default."""
    say(f"Using {client().tiers.set(tier).id}", style=Theme.OK)


@tiers_app.command("reset")
def tiers_reset() -> None:
    """Back to the default tier."""
    say(f"Using {client().tiers.reset().id}", style=Theme.OK)


credits_app = typer.Typer(help="Credits.", no_args_is_help=True)


@credits_app.command("balance")
def credits_balance(wallet: str = typer.Option("local", "--wallet")) -> None:
    """The balance of a wallet."""
    facts(client().credits.balance(wallet))


@credits_app.command("history")
@exportable("Credit history", "movements", facets=("kind",))
def credits_history(limit: int = typer.Option(20, "--limit")) -> None:
    """Credit movements, newest first."""
    table(
        client().credits.history(limit=limit),
        ["at", "wallet", "kind", "amount", "phase", "language", "note"],
        empty="No credit movements.",
    )


@credits_app.command("grants")
@exportable("Credit grants", "grants", facets=("kind", "wallet"))
def credits_grants(
    kind: str = typer.Option(None, "--kind", help="daily, promo or one_off."),
    expired: bool = typer.Option(False, "--expired", help="Include lapsed grants."),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Credits received: allowances, promotions, starter and licence bundles."""
    table(
        client().credits.grants(kind=kind, include_expired=expired, limit=limit),
        ["granted_at", "wallet", "kind", "name", "amount", "used", "remaining", "expires_at"],
        empty="No credit grants.",
    )


@credits_app.command("usage")
@exportable("Credit usage", "usage")
def credits_usage(
    by: str = typer.Option("day", "--by", help="day, source or file."),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """What was spent, by day, source or file."""
    table(
        client().credits.usage(by, limit=limit),
        ["key", "credits", "pages", "last_at"],
        empty="Nothing spent.",
    )


@credits_app.command("estimate")
def credits_estimate(target: str = typer.Argument(None)) -> None:
    """What indexing a source (or everything) would cost now."""
    facts(client().credits.estimate(_ident(target) if target else None))


@credits_app.command("redeem")
def credits_redeem(token: str) -> None:
    """Redeem a licence that carries credit grants."""
    table(client().credits.redeem_licence(token), ["kind", "amount", "wallet"])


metrics_app = typer.Typer(help="Anonymous usage statistics.", no_args_is_help=True)


@metrics_app.command("status")
def metrics_status() -> None:
    """Whether sharing is on, and what is pending."""
    facts(client().metrics.status())


@metrics_app.command("opt-in")
def metrics_opt_in() -> None:
    """Share anonymous usage statistics."""
    facts(client().metrics.opt_in())


@metrics_app.command("opt-out")
def metrics_opt_out() -> None:
    """Stop sharing."""
    facts(client().metrics.opt_out())


@metrics_app.command("preview")
def metrics_preview() -> None:
    """Exactly what would be sent."""
    dump(client().metrics.preview())


@metrics_app.command("send")
def metrics_send(force: bool = typer.Option(False, "--force")) -> None:
    """Send now."""
    facts(client().metrics.send(force))


@metrics_app.command("delete-data")
def metrics_delete() -> None:
    """Ask for the data already sent to be deleted."""
    facts(client().metrics.delete_data())


ocr_app = typer.Typer(help="OCR models and phases.", no_args_is_help=True)
models_app = typer.Typer(help="OCR model files.", no_args_is_help=True)
ocr_app.add_typer(models_app, name="models")


@models_app.command("list")
@exportable("OCR models", "models")
def models_list(language: Languages = None) -> None:
    """Models, with whether each is installed."""
    table(
        client().ocr.models.list(language or None),
        ["name", "engine", "kind", "shared", "languages", "installed", "size_bytes"],
    )


@models_app.command("download")
def models_download(language: Languages = None) -> None:
    """Download the models for languages (all enabled ones when none are given)."""
    table(client().ocr.models.download(language or None), ["name", "installed", "size_bytes"])


@models_app.command("redownload")
def models_redownload(language: Languages = None) -> None:
    """Download models again."""
    table(client().ocr.models.redownload(None, language or None), ["name", "installed"])


@models_app.command("clear")
def models_clear(
    language: Languages = None, shared: bool = typer.Option(False, "--shared")
) -> None:
    """Delete the models of languages."""
    removed = client().ocr.models.clear(language or [], include_shared=shared)
    say(f"Removed {len(removed)} model(s).", data={"removed": removed})


@models_app.command("clean")
def models_clean() -> None:
    """Delete model files nothing uses."""
    removed = client().ocr.models.clean()
    say(f"Removed {len(removed)} file(s).", data={"removed": removed})


@ocr_app.command("phases")
@exportable("OCR phases", "phases")
def ocr_phases() -> None:
    """The OCR phases (quick, moderate, deep) and whether each is installed."""
    table(client().ocr.phases.list() if hasattr(client().ocr.phases, "list") else [], ["id"])


@ocr_app.command("engines")
@exportable("OCR engines", "engines")
def ocr_engines() -> None:
    """The OCR engines."""
    value = client().ocr.engines
    table(value.list() if hasattr(value, "list") else [], ["id", "label"])


db_app = typer.Typer(help="The database.", no_args_is_help=True)


@db_app.command("integrity-check")
def db_integrity(quick: bool = typer.Option(False, "--quick")) -> None:
    """Check the database for corruption now."""
    result = client().db.integrity_check(quick=quick)
    facts(result)
    if not result.ok:
        raise typer.Exit(1)


@db_app.command("integrity-status")
def db_integrity_status() -> None:
    """The result of the last check."""
    result = client().db.integrity_status()
    if result is None:
        say("No integrity check yet.", style=Theme.DIM, data={"checked": False})
    else:
        facts(result)


logs_app = typer.Typer(help="Log files.", invoke_without_command=True, no_args_is_help=False)


@logs_app.callback()
def logs_command(
    ctx: typer.Context,
    component: str = typer.Argument("cli", help="cli, index, database, ..."),
    lines: int = typer.Option(40, "--lines", "-n"),
    level: str = typer.Option(None, "--level"),
    contains: str = typer.Option(None, "--contains"),
    follow: bool = typer.Option(False, "--follow", "-f"),
    list_: bool = typer.Option(False, "--list", help="List the log files."),
) -> None:
    """Show the end of a log file."""
    if list_:
        table(client().logs.list(), ["component", "path", "exists", "size_bytes", "modified_at"])
        return
    log = client().logs.get(component)
    if follow:
        try:
            for entry in log.follow(level=level, contains=contains):
                console.print(entry.raw)
        except KeyboardInterrupt:
            return
        return
    entries = log.tail(lines, level=level, contains=contains)
    if State.json:
        dump(entries)
    else:
        for entry in entries:
            console.print(entry.raw)


stats_app = typer.Typer(help="What has been read.", no_args_is_help=True)


@stats_app.command("show")
@exportable("Statistics", "stats")
def stats_show(
    group_by: str = typer.Option("source", "--group-by"),
    source: str = typer.Option(None, "--source"),
    since: str = typer.Option(None, "--since"),
    until: str = typer.Option(None, "--until"),
) -> None:
    """Totals by source, language, file type, engine, day ..."""
    overview = client().stats.overview(
        group_by, source=_ident(source) if source else None, since=since, until=until
    )
    if not State.json and State.export is None:
        console.print(stats_panel(overview)) if overview.rows else say(
            "Nothing has been read yet.", style=Theme.DIM
        )
        return
    table(
        overview.rows,
        ["key", "files", "pages", "native_pages", "ocr_pages", "confidence", "credits"],
        empty="Nothing has been read yet.",
    )


@stats_app.command("failures")
@exportable("Failures", "failures")
def stats_failures() -> None:
    """Failed files by reason."""
    found = client().stats.failures()
    table([{"reason": k, "files": v} for k, v in found.items()], ["reason", "files"])


@stats_app.command("low-confidence")
@exportable("Low-confidence pages", "pages", facets=("band",), paths=("file_path",))
def stats_low(limit: int = typer.Option(50, "--limit")) -> None:
    """Pages read with low confidence."""
    table(
        client().stats.low_confidence_pages(limit=limit),
        ["file_path", "page_number", "confidence", "band"],
        empty="No low-confidence pages.",
    )


updates_app = typer.Typer(help="Updates.", no_args_is_help=True)


@updates_app.command("status")
def updates_status() -> None:
    """What was last found out about updates."""
    facts(client().updates.status())


@updates_app.command("check")
def updates_check(force: bool = typer.Option(False, "--force")) -> None:
    """Look for an update now."""
    facts(client().updates.check(force))


def _outdated_addon_packages() -> list[str]:
    """Package names of installed add-ons the policy says have a newer version."""
    from vethuq.updates import _Versions  # noqa: PLC0415

    found = client()
    rules = found.policy.current().policy.addons
    names = []
    for info in found.addons.list():
        rule = rules.get(info.id)
        if rule and rule.latest and _Versions.is_older(info.version, rule.latest):
            names.append(info.name)
    return names


def update_command(
    check: bool = typer.Option(
        True, "--check/--no-check", help="Look for a newer version first (once a day at most)."
    ),
) -> None:
    """Say whether a newer VethuQ exists and print the exact steps to upgrade. Changes nothing."""
    updates = client().updates
    result = updates.check() if check else updates.status()
    try:
        addons = _outdated_addon_packages()
    except Exception:  # noqa: BLE001 - add-on information is a bonus
        addons = []
    help_ = updates.upgrade_help(addons)
    if State.json:
        dump({**result.to_dict(), **help_.to_dict()})
        return
    console.print(result.message or _update_word(result.status.value), style=Theme.OK)
    console.print(f"Installed as: {help_.kind.value}", style=Theme.DIM)
    if result.release_notes_url:
        console.print(f"Release notes: {result.release_notes_url}", style=Theme.DIM)
    for step in help_.steps:
        console.print(f"  {step}")


def _update_word(status: str) -> str:
    return {
        "up_to_date": "You have the latest version.",
        "disabled": "The update check is turned off.",
    }.get(status, "No update information yet. Run: vethuq policy refresh")


policy_app = typer.Typer(help="The signed policy.", no_args_is_help=True)


@policy_app.command("show")
def policy_show() -> None:
    """The policy in force."""
    dump(client().policy.current())


@policy_app.command("notices")
def policy_notices() -> None:
    """The notices active now."""
    found = client().policy.notices()
    table(
        found,
        ["severity", "message", "link"],
        empty="No notices.",
    )


@policy_app.command("refresh")
def policy_refresh(force: bool = typer.Option(False, "--force")) -> None:
    """Fetch the policy again."""
    facts(client().policy.refresh(force), skip=("policy",))


addons_app = typer.Typer(help="Installed add-ons.", no_args_is_help=True)


@addons_app.command("enable")
def addons_enable(addon_id: str) -> None:
    """Turn an add-on on again (applies the next time VethuQ starts)."""
    info = client().addons.set_enabled(addon_id, True)
    say(f"{info.id} is on. It runs from the next start.", data=info.to_dict())


@addons_app.command("disable")
def addons_disable(addon_id: str) -> None:
    """Turn an add-on off (applies the next time VethuQ starts)."""
    info = client().addons.set_enabled(addon_id, False)
    say(f"{info.id} is off. It stops at the next start.", data=info.to_dict())


@addons_app.command("list")
@exportable("Add-ons", "addons", facets=("status",))
def addons_list() -> None:
    """The installed add-ons and whether each is running."""
    table(client().addons.list(), ["id", "name", "version", "status", "disabled", "detail"])


def register(app: typer.Typer) -> None:
    app.add_typer(source_app, name="source")
    app.add_typer(index_app, name="index")
    app.command("search", help="Search the indexed pages.")(search_command)
    app.add_typer(search_index_app, name="search-index")
    app.add_typer(engines_app, name="search-engines")
    app.add_typer(types_app, name="file-types")
    app.add_typer(languages_app, name="languages")
    app.add_typer(tiers_app, name="tiers")
    app.add_typer(credits_app, name="credits")
    app.add_typer(metrics_app, name="metrics")
    app.add_typer(ocr_app, name="ocr")
    app.add_typer(db_app, name="db")
    app.add_typer(logs_app, name="logs")
    app.add_typer(stats_app, name="stats")
    app.command("update")(update_command)
    app.add_typer(updates_app, name="updates")
    app.add_typer(policy_app, name="policy")
    app.add_typer(addons_app, name="addons")
    app.command("version", help="Show the version.")(show_version)
