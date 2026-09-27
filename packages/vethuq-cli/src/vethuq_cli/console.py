"""Shared Rich console instances for styled CLI output.

Markup is disabled so printed content (file paths, OCR text, error
messages) is never mistaken for `[style]` tags; colors are applied via the
`style=` argument instead.
"""

from __future__ import annotations

from rich.console import Console

console = Console(highlight=False, markup=False, soft_wrap=True)
error_console = Console(stderr=True, highlight=False, markup=False, soft_wrap=True)
