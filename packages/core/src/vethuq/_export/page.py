"""The parts every HTML export shares: head, brand header, footer, cards, chips and pills."""

from __future__ import annotations

import base64
import functools
import html
import locale
from datetime import datetime
from importlib import resources

from vethuq._brand import _Brand, _Palette


class _Page:
    _TEMPLATES = resources.files("vethuq._export") / "templates"

    @staticmethod
    @functools.cache
    def template(name: str) -> str:
        """The text of one of the export's template files (`templates/<name>`)."""
        return (_Page._TEMPLATES / name).read_text(encoding="utf-8")

    @staticmethod
    def logo() -> str:
        """The logo as inline `<svg class="logo">`, so the export stays one portable file."""
        return (
            _Page.template("logo.svg")
            .strip()
            .replace("<svg ", '<svg class="logo" ', 1)
            .replace(' width="512" height="512"', ' role="img" aria-label="logo"', 1)
        )

    @staticmethod
    def favicon() -> str:
        """The logo as a `data:` URI for the browser tab."""
        data = base64.b64encode(_Page.template("logo.svg").encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{data}"

    @staticmethod
    def fill(document: str, *, kind: str, lang: str, generated_at: str) -> str:
        """Fill the parts every export shares: head, brand header (logo, name, tagline), footer."""
        shared = {
            "{{HEAD}}": _Page.template("page_head.html").rstrip("\n"),
            "{{HEADER}}": _Page.template("page_header.html").rstrip("\n"),
            "{{FOOTER}}": _Page.template("page_footer.html").rstrip("\n"),
        }
        for placeholder, text in shared.items():
            document = document.replace(placeholder, text)
        return (
            document.replace("{{LANG}}", html.escape(lang))
            .replace("{{FAVICON}}", _Page.favicon())
            .replace("{{PALETTE}}", _Palette.css_variables())
            .replace("{{STYLE}}", _Page.template("export.css").rstrip("\n"))
            .replace("{{LOGO}}", _Page.logo())
            .replace("{{KIND}}", html.escape(kind))
            .replace("{{APP_NAME}}", html.escape(_Brand.NAME))
            .replace("{{APP_TAGLINE}}", html.escape(_Brand.TAGLINE))
            .replace("{{GENERATED_AT}}", html.escape(generated_at))
        )

    @staticmethod
    def card(label: str, value: str, *, accent: bool = False) -> str:
        css = "card accent" if accent else "card"
        return (
            f'<div class="{css}"><div class="label">{html.escape(label)}</div>'
            f'<div class="value">{html.escape(value)}</div></div>'
        )

    @staticmethod
    def chip(label: str, value: str) -> str:
        key = f'<span class="k">{html.escape(label)}</span>'
        return f'<span class="chip">{key}{html.escape(value)}</span>'

    STATUS_KINDS = {
        # file statuses
        "indexed": "ok",
        "pending": "warn",
        "processing": "warn",
        "modified": "warn",
        "error": "bad",
        "removed": "muted",
        "unsupported": "muted",
        # source statuses
        "completed": "ok",
        "in_progress": "warn",
    }

    @staticmethod
    def status_pill(status: str) -> str:
        """A file or source status as a colored pill (green done, amber in flight, red failed)."""
        kind = _Page.STATUS_KINDS.get(status, "muted")
        return f'<span class="pill {kind}">{html.escape(status)}</span>'

    @staticmethod
    def generated_at() -> str:
        """The current local time, formatted per the user's locale (no ISO 'T' separator)."""
        try:
            locale.setlocale(locale.LC_TIME, "")
        except locale.Error:
            pass
        return datetime.now().astimezone().strftime("%c %Z").strip()
