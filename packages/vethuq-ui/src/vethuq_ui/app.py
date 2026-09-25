"""VethuQ desktop UI: a toolbar to add folders/files as sources, and a list of them."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from vethuq_core.db import connect
from vethuq_core.sources import SourceAlreadyExistsError, SourceError, add_source, list_sources


class MainWindow(tk.Tk):
    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        super().__init__()
        self.conn = conn or connect()

        self.title("VethuQ")
        self.geometry("720x480")

        self._build_toolbar()
        self._build_source_list()
        self.refresh_sources()

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)

        ttk.Button(toolbar, text="Add Folder", command=self.on_add_folder).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="Add File", command=self.on_add_file).pack(side=tk.LEFT, padx=2)

    def _build_source_list(self) -> None:
        columns = ("type", "status", "path")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("type", text="Type")
        self.tree.heading("status", text="Status")
        self.tree.heading("path", text="Path")
        self.tree.column("type", width=80, anchor=tk.W)
        self.tree.column("status", width=80, anchor=tk.W)
        self.tree.column("path", width=520, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

    def on_add_folder(self) -> None:
        path = filedialog.askdirectory(title="Select a folder to add to VethuQ")
        if path:
            self._add_source(path)

    def on_add_file(self) -> None:
        paths = filedialog.askopenfilenames(title="Select file(s) to add to VethuQ")
        for path in paths:
            self._add_source(path)

    def _add_source(self, path: str) -> None:
        try:
            add_source(self.conn, path)
        except SourceAlreadyExistsError:
            messagebox.showwarning("Already added", f"{path} is already registered.")
        except SourceError as exc:
            messagebox.showerror("Could not add source", str(exc))
        else:
            self.refresh_sources()

    def refresh_sources(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for source in list_sources(self.conn):
            self.tree.insert("", tk.END, values=(source.source_type, source.status, source.path))


def main() -> None:
    window = MainWindow()
    window.mainloop()


if __name__ == "__main__":
    main()
