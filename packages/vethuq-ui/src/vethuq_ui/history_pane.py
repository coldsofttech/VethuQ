"""The index-history pane shown beside the source list."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from vethuq_core.index import IndexRunner


class HistoryPane(ttk.Frame):
    """A pane of a `ttk.Panedwindow` that lists a source's past index runs.

    It adds itself to (and removes itself from) its parent paned window.
    """

    def __init__(self, paned: ttk.Panedwindow, conn: sqlite3.Connection) -> None:
        super().__init__(paned, relief=tk.SUNKEN, borderwidth=1)
        self._paned = paned
        self._conn = conn

    def show(self, source_id: str, path: str) -> None:
        # A run over "all sources" (target IS NULL) would have covered this
        # source too, so it's included alongside runs targeted at just it.
        runs = IndexRunner.list_runs(self._conn, source_id, limit=20)

        for child in self.winfo_children():
            child.destroy()
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(header, text=f"Index History — {path}").pack(side=tk.LEFT)
        ttk.Button(header, text="Close", command=self.hide).pack(side=tk.RIGHT)

        columns = ("started_at", "mode", "target", "status", "progress", "failed")
        tree = ttk.Treeview(self, columns=columns, show="headings")
        for column, heading in zip(
            columns, ("Started", "Mode", "Target", "Status", "Progress", "Failed"), strict=False
        ):
            tree.heading(column, text=heading)
        tree.column("started_at", width=150, minwidth=110, anchor=tk.W, stretch=False)
        tree.column("mode", width=80, minwidth=60, anchor=tk.W, stretch=False)
        tree.column("target", width=160, minwidth=80, anchor=tk.W, stretch=False)
        tree.column("status", width=90, minwidth=70, anchor=tk.W, stretch=False)
        tree.column("progress", width=100, minwidth=80, anchor=tk.E, stretch=False)
        tree.column("failed", width=70, minwidth=60, anchor=tk.E, stretch=False)

        hscroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(xscrollcommand=hscroll.set)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X, padx=8)
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        for run in runs:
            tree.insert(
                "",
                tk.END,
                values=(
                    self.format_timestamp(run.started_at),
                    run.mode.capitalize(),
                    run.target if run.target is not None else "All sources",
                    run.status.capitalize(),
                    f"{run.processed_files}/{run.total_files}",
                    run.failed_files,
                ),
            )

        if str(self) not in self._paned.panes():
            self._paned.add(self, weight=1)
            self._paned.update_idletasks()
            self._paned.sashpos(0, self._paned.winfo_width() // 2)

    def hide(self) -> None:
        if str(self) in self._paned.panes():
            self._paned.forget(self)

    @staticmethod
    def format_timestamp(value: str) -> str:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value
        return f"{dt.day} {dt.strftime('%b %Y %H:%M')}"
