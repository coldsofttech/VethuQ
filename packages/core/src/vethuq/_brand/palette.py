"""The app's color palette: one set of design tokens for every surface.

`palette.json` is the single source of truth, with a `light` and a `dark` scheme that
define the same tokens. The HTML export inlines it as CSS custom properties
(`--vq-<token>`), the CLI draws its Rich styles from the dark scheme (most terminals are
dark), and a future web layer can reuse `_Palette.css_variables()` as-is.
"""

from __future__ import annotations

import functools
import json
from importlib import resources


class _Palette:
    SCHEMES = ("light", "dark")
    CSS_PREFIX = "--vq-"

    @staticmethod
    @functools.cache
    def schemes() -> dict[str, dict[str, str]]:
        """`{scheme: {token: "#RRGGBB"}}`, read once from `palette.json`."""
        text = (resources.files("vethuq._brand") / "palette.json").read_text(
            encoding="utf-8"
        )
        return json.loads(text)

    @staticmethod
    def get(token: str, scheme: str = "light") -> str:
        """One token's hex color in `scheme`. Raises `KeyError` for an unknown token."""
        return _Palette.schemes()[scheme][token]

    @staticmethod
    def css_variables(selector: str = ":root") -> str:
        """CSS custom properties for both schemes: light by default, dark when the
        viewer's system prefers it. Every token is `--vq-<token>`."""

        def block(scheme: str, pad: str) -> str:
            lines = [
                f"{pad}  {_Palette.CSS_PREFIX}{token}: {value};"
                for token, value in _Palette.schemes()[scheme].items()
            ]
            return f"{pad}{selector} {{\n" + "\n".join(lines) + f"\n{pad}}}"

        return (
            block("light", "")
            + "\n@media (prefers-color-scheme: dark) {\n"
            + block("dark", "  ")
            + "\n}"
        )
