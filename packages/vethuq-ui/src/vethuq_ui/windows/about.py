"""Settings > About: a separate window with the version and environment details,
the UI's equivalent of `vethuq --version`."""

from __future__ import annotations

import tkinter as tk
from importlib import metadata
from tkinter import ttk

from vethuq_core.version import VersionInfo

from vethuq_ui.icons import Brand


class AboutWindow:
    UI_DISTRIBUTION = "vethuq-ui"
    CLI_DISTRIBUTIONS = ("vethuq-cli", "vethuq")

    COPIED_RESET_MS = 2000

    _open: tk.Toplevel | None = None

    @staticmethod
    def _distribution_version(names: tuple[str, ...]) -> str | None:
        for name in names:
            try:
                return metadata.version(name)
            except metadata.PackageNotFoundError:
                continue
        return None

    @staticmethod
    def rows() -> list[tuple[str, str]]:
        """Label/value pairs to show. The CLI row appears only when the CLI is installed."""
        details = VersionInfo.details()
        ui_version = AboutWindow._distribution_version((AboutWindow.UI_DISTRIBUTION,))
        cli_version = AboutWindow._distribution_version(AboutWindow.CLI_DISTRIBUTIONS)
        rows = [("VethuQ UI", ui_version or "unknown")]
        if cli_version is not None:
            rows.append(("VethuQ CLI", cli_version))
        rows += [
            ("Python", details.python),
            ("Platform", details.platform),
            ("Database schema", str(details.db_schema)),
            ("File types", ", ".join(details.file_types) or "none"),
            ("Search engines", ", ".join(details.search_engines) or "none"),
            ("OCR engines", ", ".join(details.ocr_engines) or "none"),
            ("Languages", ", ".join(details.ocr_languages) or "none"),
        ]
        return rows

    @staticmethod
    def _center_on(window: tk.Toplevel, parent: tk.Tk | tk.Toplevel) -> None:
        """Place `window` in the middle of `parent`."""
        window.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 2
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    @staticmethod
    def show(parent: tk.Tk | tk.Toplevel) -> None:
        """Open the About window, or bring the already-open one to the front."""
        existing = AboutWindow._open
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        rows = AboutWindow.rows()
        window = tk.Toplevel(parent)
        AboutWindow._open = window
        window.title("About VethuQ")
        window.resizable(False, False)
        window.transient(parent)
        Brand.apply_window_icon(window)

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        grid = ttk.Frame(body)
        grid.pack(fill=tk.X)
        for index, (label, value) in enumerate(rows):
            ttk.Label(grid, text=label, font=("Segoe UI", 9, "bold")).grid(
                row=index, column=0, sticky=tk.NW, padx=(0, 16), pady=2
            )
            ttk.Label(grid, text=value, wraplength=360, justify=tk.LEFT).grid(
                row=index, column=1, sticky=tk.NW, pady=2
            )

        def copy() -> None:
            window.clipboard_clear()
            window.clipboard_append("\n".join(f"{label}: {value}" for label, value in rows))
            copy_button.configure(text="Copied!")
            window.after(AboutWindow.COPIED_RESET_MS, reset_copy_label)

        def reset_copy_label() -> None:
            if copy_button.winfo_exists():
                copy_button.configure(text="Copy")

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Close", width=9, command=window.destroy).pack(side=tk.RIGHT)
        copy_button = ttk.Button(buttons, text="Copy", width=9, command=copy)
        copy_button.pack(side=tk.RIGHT, padx=(0, 6))
        AboutWindow._center_on(window, parent)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.focus_set()
