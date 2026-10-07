"""How a message names a command: `vethuq index status` in a terminal, `Index > Status` in the
interactive shell, where there is no `vethuq` to type.

Messages that point the user at another command build it with `Hints.command`, at the moment
they are shown, so the same text reads right wherever it appears. The interactive shell turns
`Hints.interactive` on; everything else leaves it off.
"""

from __future__ import annotations


class Hints:
    interactive = False

    # The interactive menu a command lives under, by the words that name it. An `<>` stands for
    # any argument (`source list <source>` is "List Files"); the longest match wins.
    MENU: dict[tuple[str, ...], str] = {
        ("search",): "Search",
        ("source", "list"): "Sources > List",
        ("source", "list", "<>"): "Sources > List Files",
        ("source", "add"): "Sources > Add",
        ("source", "remove"): "Sources > Remove",
        ("index", "run"): "Index > Run",
        ("index", "restart"): "Index > Restart",
        ("index", "status"): "Index > Status",
        ("index", "stop"): "Index > Stop",
        ("index", "pause"): "Index > Pause",
        ("index", "resume"): "Index > Resume",
        ("index", "history"): "Index > History",
        ("index", "reindex"): "Index > Reindex source",
        ("index", "reindex", "file"): "Index > Reindex file",
        ("index", "rebuild-search"): "Index > Rebuild search index",
        ("stats",): "Stats",
        ("stats", "show"): "Stats > Show",
        ("stats", "reset"): "Stats > Reset",
        ("db",): "Db",
        ("db", "integrity-check"): "Db > Integrity Check",
        ("db", "backup"): "Db > Backup",
        ("db", "backup", "create"): "Db > Backup > Create",
        ("db", "backup", "list"): "Db > Backup > List",
        ("db", "backup", "delete"): "Db > Backup > Delete",
        ("db", "restore"): "Db > Restore",
        ("db", "repair"): "Db > Repair",
        ("db", "reset"): "Db > Reset",
        ("logs",): "Logs",
        ("file-types", "list"): "File types & search engines > File types",
        ("search-engines", "list"): "File types & search engines > Search engines",
        ("settings",): "Settings",
        ("settings", "gpu"): "Settings > GPU",
        ("settings", "location"): "Settings > Location",
        ("settings", "location", "backups"): "Settings > Location > Backups",
        ("settings", "search"): "Settings > Search",
        ("settings", "search", "snippet"): "Settings > Search > Snippet",
        ("settings", "search", "export-format"): "Settings > Search > Export Format",
        ("settings", "search", "engine"): "Settings > Search > Engine",
        ("settings", "search", "fuzzy", "threshold"): "Settings > Search > Fuzzy Threshold",
        ("settings", "search", "proximity", "distance"): "Settings > Search > Proximity Distance",
        ("settings", "search", "normalize"): "Settings > Search > Normalize",
        ("settings", "search", "normalize", "case"): "Settings > Search > Normalize > Case",
        (
            "settings",
            "search",
            "normalize",
            "leetspeak",
        ): "Settings > Search > Normalize > Leetspeak",
        ("settings", "search", "normalize", "unicode"): "Settings > Search > Normalize > Unicode",
        ("settings", "search", "noise-fuzzy", "noise"): "Settings > Search > Noise Level",
        ("settings", "search", "semantic"): "Settings > Search > Semantic",
        ("settings", "search", "semantic", "threshold"): "Settings > Search > Semantic > Threshold",
        ("settings", "search", "semantic", "limit"): "Settings > Search > Semantic > Limit",
        ("settings", "search", "semantic", "combine"): "Settings > Search > Semantic > Combine",
        ("settings", "index"): "Settings > Index",
        ("settings", "index", "removed-retention"): "Settings > Index > Removed Retention",
        ("settings", "index", "thread-workers"): "Settings > Index > Thread Workers",
        ("settings", "index", "stale-lock"): "Settings > Index > Stale Lock",
        ("settings", "index", "stability-check"): "Settings > Index > Stability Check",
        ("settings", "ocr"): "Settings > Ocr",
        ("settings", "ocr", "retry"): "Settings > Ocr > Retry",
        ("settings", "ocr", "engine"): "Settings > Ocr > Engine",
        ("settings", "db"): "Settings > Db",
        ("settings", "db", "integrity-check"): "Settings > Db > Integrity Check",
        ("settings", "db", "integrity-check", "interval"): (
            "Settings > Db > Integrity Check > Interval"
        ),
        ("settings", "db", "backup"): "Settings > Db > Backup",
        ("settings", "db", "backup", "interval"): "Settings > Db > Backup > Interval",
        ("settings", "db", "backup", "retention"): "Settings > Db > Backup > Retention",
        ("settings", "logs"): "Settings > Logs",
        ("settings", "logs", "level"): "Settings > Logs > Level",
        ("settings", "logs", "retention"): "Settings > Logs > Retention",
    }

    @staticmethod
    def _words(command: str) -> tuple[list[str], list[str]]:
        """`command` (with or without `vethuq`) as its name words and the arguments after them."""
        words = command.replace("`", "").replace("'", "").split()
        if words and words[0] == "vethuq":
            words = words[1:]
        for position, word in enumerate(words):
            if word.startswith(("-", "<", "[", '"')) and position > 0:
                return words[:position], words[position:]
        return words, []

    @staticmethod
    def command(command: str) -> str:
        """`command` as a message should name it: `vethuq index status` in a terminal, its menu
        path (`Index > Status`) in the interactive shell, and - for a command that shell has no
        menu for - `vethuq ...` with a note that it is run in a terminal.

        `command` is the words as typed, with or without the leading `vethuq`; arguments after
        them are kept in a terminal and left out in the shell, which asks for them.
        """
        words, args = Hints._words(command)
        typed = " ".join(["vethuq", *words, *args])
        if not Hints.interactive:
            return typed
        first_arg = args[0] if args and args[0].startswith("<") else None
        for length in range(len(words) + (1 if first_arg else 0), 0, -1):
            key = (*words, "<>")[:length] if first_arg else tuple(words[:length])
            if key in Hints.MENU:
                return Hints.MENU[key]
        return f"{typed} (in a terminal)"
