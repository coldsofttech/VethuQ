"""`vethuq search <content>` command for searching indexed OCR content."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import RenderableType
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from vethuq_core.hints import Hints
from vethuq_core.search import (
    Export,
    PageResult,
    Search,
    SearchEngineUnavailable,
    SearchLanguageError,
    SearchMatch,
    SearchOptionError,
    SearchOptions,
    SearchQueryError,
)
from vethuq_core.search.engines import Ranking
from vethuq_core.settings import InvalidSettingValueError, SearchSettings
from vethuq_core.storage import Storage, open_storage

from vethuq_cli.console import console, error_console
from vethuq_cli.search.pager import Pager
from vethuq_cli.search.renderer import ResultRenderer
from vethuq_cli.theme import Theme

_NO_MATCH_HINTS = {
    "exact": "`exact` only finds the text as typed, as a whole word. "
    "Try `--engine like` to match part of a word or ignore case.",
    "full-text": "`full-text` only finds whole words (add `*` for a prefix, e.g. `mus*`). "
    "Try `--engine like` to match part of a word.",
    "fuzzy": "`fuzzy` only finds whole words close to yours (words under 4 letters and "
    "numbers must match exactly). Try `--fuzziness loose` or `--engine like`.",
    "proximity": "`proximity` needs every word within the distance of the others, as whole "
    "words. Try `--distance loose` or `--engine full-text`.",
    "noise-fuzzy": "`noise-fuzzy` finds your characters hidden by a little stray punctuation or "
    "whitespace, look-alike symbols and a typo or two - not letters in between. Try "
    "`--noise medium` (or `high`), `--fuzziness loose` or `--leet-level extended`.",
    "semantic": "`semantic` only finds passages whose meaning is close enough to yours. Try "
    "`--fuzziness loose` (or a lower --threshold), more words describing what you mean, or "
    "`vethuq settings search semantic combine full-text` to also match your exact words.",
}

# The interactive search asks for these as prompts, so its hints point at the prompt, not a flag.
_NO_MATCH_HINTS_INTERACTIVE = {
    "exact": "`exact` only finds the text as typed, as a whole word. "
    "Try the `like` engine to match part of a word or ignore case.",
    "full-text": "`full-text` only finds whole words (add `*` for a prefix, e.g. `mus*`). "
    "Try the `like` engine to match part of a word.",
    "fuzzy": "`fuzzy` only finds whole words close to yours (words under 4 letters and "
    "numbers must match exactly). Try a looser fuzziness or the `like` engine.",
    "proximity": "`proximity` needs every word within the distance of the others, as whole "
    "words. Try a looser distance or the `full-text` engine.",
    "noise-fuzzy": "`noise-fuzzy` finds your characters hidden by a little stray punctuation or "
    "whitespace, look-alike symbols and a typo or two - not letters in between. Try "
    "a higher noise, a looser fuzziness or an extended leet level.",
    "semantic": "`semantic` only finds passages whose meaning is close enough to yours. Try "
    "a looser closeness, more words describing what you mean, or set "
    "Settings > Search > Semantic > Combine to also match your exact words.",
}


_NORMALIZERS = {"unicode": "unicode", "case": "case", "leetspeak": "leetspeak", "leet": "leetspeak"}


def _apply_normalize(
    entries: list[str] | None,
    case_sensitive: bool | None,
    leet_level: str | None,
    unicode: str | None,
) -> tuple[bool | None, str | None, str | None]:
    """`--normalize NAME=VALUE[,NAME=VALUE...]` folded into the options it stands for.

    `case=match|ignore` is `--case-sensitive` / `--no-case-sensitive`, `leetspeak=LEVEL` is
    `--leet-level` and `unicode=LEVEL` is the Unicode normalization; giving the same one twice
    is an error.
    """
    for entry in entries or []:
        for part in entry.split(","):
            name, separator, value = part.partition("=")
            normalizer = _NORMALIZERS.get(name.strip().lower())
            if not separator or normalizer is None or not value.strip():
                raise typer.BadParameter(
                    f"{part!r} is not NAME=VALUE with NAME one of unicode, case, leetspeak.",
                    param_hint="--normalize",
                )
            value = value.strip().lower()
            if normalizer == "case":
                if value not in ("ignore", "match"):
                    raise typer.BadParameter(
                        "case must be one of ignore, match.", param_hint="--normalize"
                    )
                if case_sensitive is not None:
                    raise typer.BadParameter(
                        "case is given twice (--normalize and --case-sensitive).",
                        param_hint="--normalize",
                    )
                case_sensitive = value == "match"
            elif normalizer == "leetspeak":
                if leet_level is not None:
                    raise typer.BadParameter(
                        "leetspeak is given twice (--normalize and --leet-level).",
                        param_hint="--normalize",
                    )
                leet_level = value
            else:
                if unicode is not None:
                    raise typer.BadParameter(
                        "unicode is given twice in --normalize.", param_hint="--normalize"
                    )
                unicode = value
    return case_sensitive, leet_level, unicode


def _resolve_options(
    storage: Storage,
    engine: str | None,
    case_sensitive: bool | None,
    threshold: str | None,
    fuzziness: str | None,
    distance: str | None,
    leet_level: str | None = None,
    noise: str | None = None,
    unicode: str | None = None,
) -> SearchOptions:
    """`Search.resolve_options`, with an unusable combination reported as a usage error.

    `fuzziness` is the preset-name form of `threshold`; giving both is an error.
    """
    if fuzziness is not None:
        if threshold is not None:
            raise typer.BadParameter(
                "give either --threshold or --fuzziness, not both.", param_hint="--fuzziness"
            )
        if fuzziness.strip().lower() not in SearchSettings.FUZZY_PRESETS:
            raise typer.BadParameter(
                f"{fuzziness!r} is not one of {', '.join(SearchSettings.FUZZY_PRESETS)}.",
                param_hint="--fuzziness",
            )
        # The name, not its number: each engine has its own presets for it.
        threshold = fuzziness.strip().lower()
    try:
        return Search.resolve_options(
            storage, engine, case_sensitive, threshold, distance, leet_level, noise, unicode
        )
    except SearchOptionError as exc:
        if exc.option == "engine":
            hint = "--engine"
        elif exc.option == "threshold":
            hint = "--fuzziness" if fuzziness is not None else "--threshold"
        elif exc.option == "distance":
            hint = "--distance"
        elif exc.option == "level":
            hint = "--leet-level"
        elif exc.option == "noise":
            hint = "--noise"
        elif exc.option == "unicode":
            hint = "--normalize"
        else:
            hint = "--case-sensitive" if case_sensitive else "--no-case-sensitive"
        raise typer.BadParameter(str(exc), param_hint=hint) from exc


class SearchHelp:
    TEXT = (
        "Search indexed content for CONTENT and print matching pages. Only successfully "
        "indexed documents are searched.\n\n"
        "--engine picks how CONTENT is matched:\n\n"
        "all (the default) - runs every engine and lists each page once, ranked by the "
        "strictest way it matched: Exact, Contains, Relevant, Near, Word, Similar, "
        "then Obscured. A hit that needed look-alikes or accent folding ranks after those "
        "matched as typed and says so (Contains · look-alike). Each page is labelled with "
        "that, the other engines that found it, and any hit found less strictly than the "
        "page's best. Each engine applies the "
        "options it can.\n\n"
        "like - finds CONTENT anywhere, even inside a word, ignoring case. "
        '`mus` finds "Museum". With --leet-level (or `vethuq settings search normalize '
        "leetspeak`) look-alike characters count as the letters they stand for, both ways: "
        "`hello` finds `h3ll0` and `p@55w0rd` finds `password`. Results are ordered by file "
        "path.\n\n"
        "lexical - finds CONTENT anywhere, even inside a word, like `like`, but lists the "
        "best-matching pages first. Needs at least 3 characters.\n\n"
        "exact - finds CONTENT exactly as typed: same case, as a whole word. `Museum` finds "
        '"Museum" but not "museum" or "Museums". Always case-sensitive.\n\n'
        "full-text - finds pages containing all your words, in any order, ignoring case and "
        'matching English word forms such as plurals (`museum` finds "Museums"). Quote a '
        '"phrase" to keep words together, and end a word with * for a prefix (`mus*`). Best '
        "matches first. Never case-sensitive.\n\n"
        "fuzzy - finds words close to yours, tolerating typos and OCR misreads (`Musuem` or "
        "`Museurn` for `Museum`). Every word must be matched, as close as --threshold or "
        "--fuzziness allows; words under 4 letters and anything with a digit must match "
        "exactly. Closest matches first.\n\n"
        "proximity - finds passages where all your words (at least two, any order; quote a "
        '"phrase" to keep words together) sit within --distance words of each other, such '
        "as `payment` and `termination` in the same clause. One result per passage, best "
        "pages first. Never case-sensitive.\n\n"
        "noise-fuzzy - finds CONTENT's characters hidden by stray punctuation or whitespace, "
        "look-alike symbols and typos, all at once: `h..e llo`, `h @ e # l l o`, `h3ll0` and "
        "`helo` all find `hello`. The noise is ignored (letters never are), look-alikes are "
        "folded (single characters of --leet-level) and what is left must be within "
        "--threshold or --fuzziness of CONTENT, as in `fuzzy`. How much noise is skipped is "
        "set by --noise (low, medium or high) or `vethuq settings search noise-fuzzy noise`. "
        "Honours --case-sensitive; the cleanest text first.\n\n"
        "semantic - finds passages that MEAN what CONTENT means, whatever the wording or "
        'language: `refund policy` finds "customers may return goods for a full '
        'reimbursement", and a Telugu query finds the English page that says the same. '
        "Needs the `search-semantic` extra and a language model (multilingual-e5-small) that "
        "downloads the first time it is used, and every page is read once into the semantic "
        "index (`vethuq semantic index` does it ahead of time). --threshold or --fuzziness "
        "sets how close in meaning a passage must be, `vethuq settings search semantic limit` "
        "how many pages come back, and `vethuq settings search semantic combine` ranks the "
        "pages of `full-text` or `lexical` together with it. Never case-sensitive.\n\n"
        "--normalize decides what counts as the same character, whichever engine matches: "
        "unicode=full folds accents and compatibility forms (`cafe` finds `café`), case=match "
        "or ignore, leetspeak=basic|standard|extended reads look-alikes as letters. They are "
        "also the settings under `vethuq settings search normalize`, which each engine's own "
        "defaults fill in; `exact` only takes them when asked for here.\n\n"
        "Results open in a pager at the top: scroll (e.g. the down arrow) to reveal more, "
        "`e` to export what's been found and close the pager, `h` (with the default `all` "
        "engine) to see what Exact, Contains, Relevant, Near, Word, Similar and "
        "Obscured (and the look-alike and accents modifiers) mean, `q` to close "
        "without exporting. A file with several matching pages prints its file name as a bold "
        "heading and its `File:` path line once, followed by one `Page: X of Y` and a "
        "boxed, highlighted snippet per match; consecutive files alternate accent colors. "
        "How much context the box shows is set by `vethuq settings search snippet`.\n\n"
        "With --export, results are written to that file as JSON or HTML instead of being "
        "printed here."
    )


def search(
    content: str = typer.Argument(..., help="Text to search for in indexed content."),
    engine: str | None = typer.Option(
        None,
        "--engine",
        help=(
            "How to match: 'all' (every engine at once, the pages ranked together - the "
            "default), 'like' (substring, even inside a word), 'exact' (as typed, "
            "case-sensitive, whole word), 'full-text' (whole words, stemmed, best match "
            "first), 'fuzzy' (whole words close to yours, tolerating typos and OCR "
            "misreads), 'proximity' (all your words near each other), 'noise-fuzzy' (words "
            "hidden by stray characters, look-alikes and typos at once, e.g. h..e l1o) or "
            "'semantic' (passages that mean what you asked, in any wording or language). "
            "Defaults to "
            "`vethuq settings search engine`."
        ),
    ),
    case_sensitive: bool | None = typer.Option(
        None,
        "--case-sensitive/--no-case-sensitive",
        help=(
            "Match case. Only 'like', 'lexical', 'fuzzy' and 'noise-fuzzy' honour it "
            "(default: "
            "`vethuq settings search normalize case`); 'exact' is always case-sensitive, "
            "'full-text', 'proximity' and 'semantic' never are. With 'all', each engine "
            "applies what it can."
        ),
    ),
    threshold: str | None = typer.Option(
        None,
        "--threshold",
        help=(
            "Fuzzy, noise-fuzzy and semantic only: the minimum similarity between your words and "
            "the words found (semantic: between what you mean and the passage), as a "
            "percentage (80%) or a number above 0 and up to 1 (0.8). Default: `vethuq settings "
            "search fuzzy threshold` (semantic: `vethuq settings search semantic threshold`)."
        ),
    ),
    fuzziness: str | None = typer.Option(
        None,
        "--fuzziness",
        help=(
            "Fuzzy, noise-fuzzy and semantic only: a named --threshold - 'strict', 'balanced' "
            "or 'loose' (fuzzy: 0.90, 0.80, 0.65; semantic: 0.86, 0.80, 0.75)."
        ),
    ),
    distance: str | None = typer.Option(
        None,
        "--distance",
        help=(
            "Proximity only: the most words between your first and last word - a number from "
            "1 to 100, or 'tight' (3), 'medium' (10) or 'loose' (30). Default: `vethuq "
            "settings search proximity distance`."
        ),
    ),
    leet_level: str | None = typer.Option(
        None,
        "--leet-level",
        help=(
            "Like and noise-fuzzy only: which look-alike characters count as the letters "
            "they stand for - 'off', 'basic', 'standard' or 'extended'. Default: `vethuq "
            "settings search normalize leetspeak` (off for like, basic for noise-fuzzy)."
        ),
    ),
    normalize: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--normalize",
        help=(
            "What counts as the same character, as NAME=VALUE (repeat, or separate with commas): "
            "unicode=off|basic|full (basic composes characters, full also folds accents and "
            "compatibility forms - like, exact, fuzzy and noise-fuzzy; by default basic for like "
            "and exact, full for fuzzy and noise-fuzzy), case=ignore|match (the "
            "same as --no-case-sensitive / --case-sensitive) and leetspeak=off|basic|standard|"
            "extended (the same as --leet-level). Defaults: `vethuq settings search normalize`."
        ),
    ),
    noise: str | None = typer.Option(
        None,
        "--noise",
        help=(
            "Noise-fuzzy only: how much stray punctuation and whitespace may sit inside a "
            "match - 'low' (1 in a row, 2 in all), 'medium' (3, 6) or 'high' (6, 12). "
            "Default: `vethuq settings search noise-fuzzy noise`."
        ),
    ),
    lang: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--lang",
        help=(
            "Only results on pages that were read in this language ('te', 'en', or 'en,te'; "
            "repeat or comma-separate). A page read in two languages counts for both. "
            "Default: every language. Any known language works, installed or not."
        ),
    ),
    export: str | None = typer.Option(
        None,
        "--export",
        help=(
            "Also export results to this file, instead of printing them here. The format "
            "defaults to `vethuq settings search export-format` unless --format overrides it."
        ),
    ),
    format_: str | None = typer.Option(
        None,
        "--format",
        help="Export format: 'json' or 'html'. Only used with --export.",
    ),
) -> None:
    """Search indexed content for CONTENT and print matching pages."""
    storage = open_storage()
    try:
        case_sensitive, leet_level, unicode = _apply_normalize(
            normalize, case_sensitive, leet_level, None
        )
        options = _resolve_options(
            storage,
            engine,
            case_sensitive,
            threshold,
            fuzziness,
            distance,
            leet_level,
            noise,
            unicode,
        )
        pages: list[PageResult] | None = None
        languages = ",".join(lang) if lang else None
        try:
            if options.engine == SearchSettings.ENGINE_ALL:
                pages = Search.indexed_pages(
                    storage,
                    content,
                    case_sensitive=options.case_sensitive,
                    threshold=options.threshold,
                    distance=options.distance,
                    level=options.level,
                    noise=options.noise,
                    unicode=options.unicode,
                    languages=languages,
                )
                matches = Ranking.flatten(pages)
            else:
                matches = Search.indexed_content(
                    storage,
                    content,
                    engine=options.engine,
                    case_sensitive=options.case_sensitive,
                    threshold=options.threshold,
                    distance=options.distance,
                    level=options.level,
                    noise=options.noise,
                    unicode=options.unicode,
                    languages=languages,
                )
        except SearchLanguageError as exc:
            raise typer.BadParameter(str(exc), param_hint="--lang") from exc
        except SearchQueryError as exc:
            raise typer.BadParameter(str(exc), param_hint="CONTENT") from exc
        except SearchEngineUnavailable as exc:
            error_console.print(f"Error: {exc}", style=Theme.ERROR)
            raise typer.Exit(code=1) from exc
        if not matches:
            message = Text("No matches found.", style=Theme.NOTICE)
            hints = _NO_MATCH_HINTS_INTERACTIVE if Hints.interactive else _NO_MATCH_HINTS
            if options.engine in hints:
                message.append(f"\n\n{hints[options.engine]}", style="bright_black")
            console.print(ResultRenderer.message_panel(message, Theme.NOTICE))
            return

        if export is not None:
            try:
                resolved_format = SearchSettings.resolve_export_format(storage, format_)
            except InvalidSettingValueError as exc:
                error_console.print(f"Error: {exc}", style=Theme.ERROR)
                raise typer.Exit(code=1) from exc
            output_path = Path(export)
            Export.search_results(
                matches,
                content,
                output_path,
                resolved_format,
                engine=options.engine,
                case_sensitive=options.case_sensitive,
                threshold=options.threshold,
                distance=options.distance,
                level=options.level,
                noise=options.noise,
                unicode=options.unicode,
            )
            console.print(
                ResultRenderer.message_panel(
                    Text.assemble(
                        ("Exported ", "white"),
                        (str(len(matches)), Theme.VALUE),
                        (f" match(es) to {output_path} ({resolved_format}).", "white"),
                    ),
                    Theme.OK,
                )
            )
            return

        def _export_from_pager() -> None:
            output = Prompt.ask("Export to file", console=console).strip()
            if not output:
                console.print("Export cancelled.", style="bright_black")
                return
            resolved_format = Prompt.ask(
                "Export format",
                console=console,
                default=SearchSettings.get_export_format(storage),
                choices=list(SearchSettings.EXPORT_FORMATS),
            ).strip()
            output_path = Path(output)
            Export.search_results(
                matches,
                content,
                output_path,
                resolved_format,
                engine=options.engine,
                case_sensitive=options.case_sensitive,
                threshold=options.threshold,
                distance=options.distance,
                level=options.level,
                noise=options.noise,
                unicode=options.unicode,
            )
            console.print(
                ResultRenderer.message_panel(
                    Text.assemble(
                        ("Exported ", "white"),
                        (str(len(matches)), Theme.VALUE),
                        (f" match(es) to {output_path} ({resolved_format}).", "white"),
                    ),
                    Theme.OK,
                )
            )

        items: list[SearchMatch] | list[PageResult]
        if pages is not None:
            items, title = pages, ResultRenderer.page_heading(len(pages), options)
        else:
            items, title = matches, ResultRenderer.heading(len(matches), options)

        def entries_for(item: SearchMatch | PageResult, accent: str) -> list[RenderableType]:
            if isinstance(item, PageResult):
                return ResultRenderer.page_entries(item, accent)
            return ResultRenderer.match_entries(item, options, accent)

        file_panels: list[Panel] = []
        entries: list[RenderableType] = []
        first: SearchMatch | PageResult | None = None
        last_file_path: str | None = None
        accent = ResultRenderer.ACCENT_STYLES[0]

        def _close_file() -> None:
            if first is not None:
                file_panels.append(ResultRenderer.file_panel(first, accent, entries))

        for item in items:
            if item.file_path != last_file_path:
                _close_file()
                accent = ResultRenderer.ACCENT_STYLES[
                    len(file_panels) % len(ResultRenderer.ACCENT_STYLES)
                ]
                first, last_file_path, entries = item, item.file_path, []
            entries.extend(entries_for(item, accent))
        _close_file()

        with console.capture() as capture:
            console.print(ResultRenderer.results_panel(title, file_panels))
        help_text = None
        if pages is not None:  # only the combined search labels its matches
            with console.capture() as legend:
                console.print(ResultRenderer.legend())
            help_text = legend.get()
        Pager.page(capture.get(), _export_from_pager, help_text)
    finally:
        storage.close()
