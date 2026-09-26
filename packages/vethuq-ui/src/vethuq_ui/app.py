"""VethuQ desktop UI: a toolbar to add folders/files as sources, and a list of them."""

from __future__ import annotations

import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from vethuq_core.db import connect
from vethuq_core.ocr import run_ocr
from vethuq_core.sources import SourceAlreadyExistsError, SourceError, add_source, list_sources

_INDEX_POLL_INTERVAL_MS = 5000


class MainWindow(tk.Tk):
    def __init__(
        self, conn: sqlite3.Connection | None = None, db_path: Path | None = None
    ) -> None:
        super().__init__()
        self.conn = conn or connect(db_path)
        self._db_path = db_path

        self.title("VethuQ")
        self.geometry("720x480")

        self._build_toolbar()
        self._build_source_list()
        self.refresh_sources()
        self._start_index_worker()

    def _start_index_worker(self) -> None:
        self._worker_stop = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._index_worker_loop, daemon=True
        )
        self._worker_thread.start()

    def _index_worker_loop(self) -> None:
        # Runs on a background thread with its own connection — sqlite3
        # connections aren't safe to share across threads.
        worker_conn = connect(self._db_path)
        try:
            while not self._worker_stop.wait(_INDEX_POLL_INTERVAL_MS / 1000):
                pending = [s for s in list_sources(worker_conn) if s.status == "pending"]
                for source in pending:
                    run_ocr(worker_conn, source)
                    self.after(0, self.refresh_sources)
        finally:
            worker_conn.close()

    def destroy(self) -> None:
        self._worker_stop.set()
        super().destroy()

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
