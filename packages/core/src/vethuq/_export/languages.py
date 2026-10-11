"""Which language a piece of text is written in, judged by script, from the installed languages."""

from __future__ import annotations

import re
from collections.abc import Callable

from vethuq_addon_api import LanguageSpec


class _ExportLanguages:
    """Reads the languages add-ons provide (`LanguageSpec.script_ranges`).

    Every language counts, installed and usable or not: a file read when Telugu was installed still
    is Telugu in an export made after it was removed. Text with no letters of any known script
    (digits, punctuation) is in no language.
    """

    # Zero-width (non-)joiners sit inside words of some scripts (they choose a conjunct's form).
    JOINERS = "‌‍"

    def __init__(self, specs: Callable[[], list[LanguageSpec]]) -> None:
        self._specs = specs

    def specs(self) -> list[LanguageSpec]:
        return list(self._specs())

    def default(self) -> LanguageSpec | None:
        found = self.specs()
        return next((s for s in found if s.default), found[0] if found else None)

    @staticmethod
    def _body(spec: LanguageSpec) -> str:
        return "".join(f"{re.escape(chr(a))}-{re.escape(chr(b))}" for a, b in spec.script_ranges)

    def in_text(self, text: str) -> list[str]:
        """The ids of the languages `text` is written in, in the order the languages are listed."""
        found = []
        for spec in self.specs():
            if spec.script_ranges and re.search(f"[{self._body(spec)}]", text):
                found.append(spec.id)
        return found

    def ordered(self, ids: list[str]) -> list[str]:
        """`ids` in the order the languages are listed, repeats dropped."""
        wanted = set(ids)
        return [s.id for s in self.specs() if s.id in wanted]

    def document(self, ids: list[str]) -> str:
        """The `<html lang>`: the one language used, else the default (others are tagged inline)."""
        if len(ids) == 1:
            return ids[0]
        default = self.default()
        return default.id if default else "en"

    def names(self, ids: list[str]) -> str:
        labels = {s.id: s.label for s in self.specs()}
        return ", ".join(labels.get(i, i) for i in ids)

    def tag(self, escaped: str) -> str:
        """Wrap each run of non-default-language text in `<span lang="..">`, so a browser picks that
        language's font and shaping inside a page in the default one. `escaped` is already
        HTML-safe; text in the default language is returned untouched."""
        default = self.default()
        for spec in self.specs():
            if not spec.script_ranges or (default is not None and spec.script == default.script):
                continue
            body = self._body(spec)
            run = re.compile(f"[{body}][{body}{self.JOINERS} ]*(?<! )")
            escaped = run.sub(f'<span lang="{spec.id}">\\g<0></span>', escaped)
        return escaped
