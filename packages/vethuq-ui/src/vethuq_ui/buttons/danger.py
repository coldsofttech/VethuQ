"""The red button for destructive actions."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk
from vethuq_core.branding import Palette


class DangerButtonStyle:
    """A ttk button style in the palette's `danger` red. sv_ttk draws its buttons from images
    and can't recolour them, so this draws matching rounded images (same 4px corners as its
    own buttons) and registers them as a ttk element."""

    STYLE = "Danger.TButton"
    _ELEMENT = "DangerButton.button"
    _SIZE = 24
    _RADIUS = 4
    _SCALE = 4
    _installed_on: tk.Misc | None = None
    _images: list[ImageTk.PhotoImage] = []

    @staticmethod
    def _shade(color: str, factor: float) -> str:
        red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
        return f"#{int(red * factor):02X}{int(green * factor):02X}{int(blue * factor):02X}"

    @staticmethod
    def _image(fill: str, outline: str | None = None) -> ImageTk.PhotoImage:
        size = DangerButtonStyle._SIZE * DangerButtonStyle._SCALE
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).rounded_rectangle(
            (0, 0, size - 1, size - 1),
            radius=DangerButtonStyle._RADIUS * DangerButtonStyle._SCALE,
            fill=fill,
            outline=outline,
            width=DangerButtonStyle._SCALE,
        )
        canvas = canvas.resize(
            (DangerButtonStyle._SIZE, DangerButtonStyle._SIZE), Image.Resampling.LANCZOS
        )
        return ImageTk.PhotoImage(canvas)

    @staticmethod
    def ensure(widget: tk.Misc) -> str:
        """Register the style once for the app (styles are shared by every window) and return
        its name."""
        root = widget.nametowidget(".")
        if DangerButtonStyle._installed_on is root:
            return DangerButtonStyle.STYLE
        danger = Palette.get("danger")
        normal = DangerButtonStyle._image(danger)
        hover = DangerButtonStyle._image(DangerButtonStyle._shade(danger, 0.9))
        pressed = DangerButtonStyle._image(DangerButtonStyle._shade(danger, 0.8))
        disabled = DangerButtonStyle._image(Palette.get("surface-alt"), Palette.get("border"))
        DangerButtonStyle._images = [normal, hover, pressed, disabled]  # keep them alive
        style = ttk.Style(root)
        style.element_create(
            DangerButtonStyle._ELEMENT,
            "image",
            normal,
            ("disabled", disabled),
            ("pressed", pressed),
            ("active", hover),
            border=DangerButtonStyle._RADIUS,
            sticky="nswe",
        )
        style.layout(
            DangerButtonStyle.STYLE,
            [
                (
                    DangerButtonStyle._ELEMENT,
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Button.padding",
                                {
                                    "sticky": "nswe",
                                    "children": [
                                        ("Button.label", {"expand": "1", "sticky": "nswe"})
                                    ],
                                },
                            )
                        ],
                    },
                )
            ],
        )
        style.configure(
            DangerButtonStyle.STYLE,
            padding=(8, 2, 8, 3),
            foreground=Palette.get("on-primary"),
            anchor=tk.CENTER,
        )
        style.map(DangerButtonStyle.STYLE, foreground=[("disabled", Palette.get("text-muted"))])
        DangerButtonStyle._installed_on = root
        return DangerButtonStyle.STYLE
