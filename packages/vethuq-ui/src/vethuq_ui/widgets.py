"""Small helpers shared by the views for building themed ttk widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from vethuq_ui.icons import get_icon


class Widgets:
    @staticmethod
    def icon_button_kwargs(
        name: str, glyph: str, caption: str, *, compound: str = tk.TOP, size: int | None = None
    ) -> dict[str, Any]:
        """Button/Checkbutton kwargs for an icon+caption control: a real icon
        if `assets/icons/<name>.png` exists yet, else the old glyph-in-text
        look. `compound` places the icon relative to the text (`tk.TOP` for
        the ribbon's icon-above-caption buttons, `tk.LEFT` for an inline one
        like the search bar's Go button). `size` defaults to the ribbon tab
        buttons' 32px (see `get_icon`); pass 16 for an inline control like
        Go, to match the file-type badges' size.
        """
        icon = get_icon(name) if size is None else get_icon(name, size)
        if icon is not None:
            return {"image": icon, "text": caption, "compound": compound}
        separator = "\n" if compound == tk.TOP else " "
        return {"text": f"{glyph}{separator}{caption}"}

    @staticmethod
    def flush_left_tree_style(root: tk.Misc, style_name: str) -> None:
        """A Treeview style with no indicator/indent, so a row's own image
        (e.g. a file-type or source-type icon) sits flush against the left edge."""
        style = ttk.Style(root)
        style.configure(style_name, indent=0)
        style.layout(
            f"{style_name}.Item",
            [
                (
                    "Treeitem.padding",
                    {
                        "sticky": "nswe",
                        "children": [
                            ("Treeitem.image", {"side": "left", "sticky": ""}),
                            ("Treeitem.text", {"side": "left", "sticky": ""}),
                        ],
                    },
                )
            ],
        )
