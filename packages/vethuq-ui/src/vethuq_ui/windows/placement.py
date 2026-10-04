"""Where standalone windows appear."""

from __future__ import annotations

import tkinter as tk


class Placement:
    @staticmethod
    def center_on(window: tk.Toplevel, parent: tk.Tk | tk.Toplevel) -> None:
        """Place `window` in the middle of `parent`."""
        window.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 2
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
