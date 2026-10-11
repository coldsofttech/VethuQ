"""Shared Rich consoles. Markup is off so file paths, OCR text and messages are never mistaken for
`[style]` tags; colour is applied with `style=`."""

from __future__ import annotations

from rich.console import Console

console = Console(highlight=False, markup=False, soft_wrap=True)
error_console = Console(stderr=True, highlight=False, markup=False, soft_wrap=True)


class Theme:
    ERROR = "bold red"
    OK = "bold green"
    WARN = "yellow"
    LABEL = "cyan"
    DIM = "bright_black"
    HIT = "bold black on yellow"
