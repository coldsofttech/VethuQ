"""Where standalone windows appear."""

from __future__ import annotations

import tkinter as tk


class Placement:
    @staticmethod
    def center_on_main(window: tk.Toplevel) -> None:
        """Place `window` in the middle of the main window, however deeply it was opened."""
        Placement.center_on(window, window.nametowidget("."))

    @staticmethod
    def center_on(window: tk.Toplevel, parent: tk.Tk | tk.Toplevel) -> None:
        """Place `window` in the middle of `parent`, counting both windows' title bars and
        borders so the whole frames line up, not just their contents."""
        window.update_idletasks()
        parent.update_idletasks()
        border = parent.winfo_rootx() - parent.winfo_x()
        title = parent.winfo_rooty() - parent.winfo_y()
        centre_x = parent.winfo_x() + (parent.winfo_width() + 2 * border) // 2
        centre_y = parent.winfo_y() + (parent.winfo_height() + title + border) // 2
        # The new window is not mapped yet, so assume it is framed like its parent.
        x = centre_x - (window.winfo_reqwidth() + 2 * border) // 2
        y = centre_y - (window.winfo_reqheight() + title + border) // 2
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
