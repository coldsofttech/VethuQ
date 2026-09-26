"""VethuQ desktop UI: Settings > Sources to add folders/files and manage registered sources."""

from __future__ import annotations

import multiprocessing
import queue
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from vethuq_core.db import connect
from vethuq_core.settings import is_gpu_enabled, set_gpu_enabled
from vethuq_core.sources import (
    SourceAlreadyExistsError,
    SourceError,
    SourceNotFoundError,
    add_source,
    list_sources,
    remove_source,
)

_INDEX_POLL_INTERVAL_MS = 5000
_QUEUE_POLL_INTERVAL_MS = 100


def _run_index_worker(
    db_path: Path | None,
    stop_event: multiprocessing.synchronize.Event,
    message_queue: multiprocessing.Queue,
) -> None:
    """Poll for pending sources and OCR them, in a process of its own.

    This runs as a separate OS process rather than a thread because
    PaddleOCR's native calls don't reliably release the GIL — in a thread,
    a long init/inference call would block the main process's Tk event
    loop for as long as it runs, freezing the whole UI. Status updates are
    reported back through `message_queue`; nothing here ever touches Tk,
    and it must stay a plain module-level function (not a bound method) so
    it's picklable for `multiprocessing`'s spawn start method on Windows.
    """
    from vethuq_core.ocr import run_ocr

    worker_conn = connect(db_path)
    try:
        while not stop_event.wait(_INDEX_POLL_INTERVAL_MS / 1000):
            pending = [s for s in list_sources(worker_conn) if s.status == "pending"]
            for index, source in enumerate(pending, start=1):
                message_queue.put(("indexing", index, len(pending), source.path))
                run_ocr(worker_conn, source)
                message_queue.put(("refresh",))
            message_queue.put(("idle",))
    finally:
        worker_conn.close()


class MainWindow(tk.Tk):
    def __init__(
        self, conn: sqlite3.Connection | None = None, db_path: Path | None = None
    ) -> None:
        super().__init__()
        self.conn = conn or connect(db_path)
        self._db_path = db_path

        self.title("VethuQ")
        self.geometry("720x480")

        self._build_menubar()
        self._build_status_bar()
        self._build_source_list()
        self.refresh_sources()
        self._closing = False
        self._start_index_worker()
        self.after(_QUEUE_POLL_INTERVAL_MS, self._process_worker_queue)

    def _start_index_worker(self) -> None:
        self._worker_stop = multiprocessing.Event()
        self._worker_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._worker_process = multiprocessing.Process(
            target=_run_index_worker,
            args=(self._db_path, self._worker_stop, self._worker_queue),
            daemon=True,
        )
        self._worker_process.start()

    def _process_worker_queue(self) -> None:
        while True:
            try:
                message = self._worker_queue.get_nowait()
            except queue.Empty:
                break
            tag = message[0]
            if tag == "indexing":
                _, index, total, path = message
                self._set_indexing_status(index, total, path)
            elif tag == "refresh":
                self.refresh_sources()
            elif tag == "idle":
                self._set_idle_status()
        if not self._closing:
            self.after(_QUEUE_POLL_INTERVAL_MS, self._process_worker_queue)

    def destroy(self) -> None:
        self._closing = True
        self._worker_stop.set()
        super().destroy()

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Sources", command=self.on_show_source_list)
        settings_menu.add_separator()
        self._gpu_enabled_var = tk.BooleanVar(value=is_gpu_enabled(self.conn))
        settings_menu.add_checkbutton(
            label="Use GPU (if available)",
            variable=self._gpu_enabled_var,
            command=self._on_toggle_gpu,
        )
        menubar.add_cascade(label="Settings", menu=settings_menu)

        self.config(menu=menubar)

    def _on_toggle_gpu(self) -> None:
        set_gpu_enabled(self.conn, self._gpu_enabled_var.get())

    def _build_source_list(self) -> None:
        self._source_list_frame = ttk.Frame(self)

        toolbar = ttk.Frame(self._source_list_frame)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        ttk.Button(toolbar, text="Add Folder", command=self.on_add_folder).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="Add File", command=self.on_add_file).pack(side=tk.LEFT, padx=2)
        self._delete_button = ttk.Button(
            toolbar, text="Delete", command=self._delete_selected_source, state=tk.DISABLED
        )
        self._delete_button.pack(side=tk.LEFT, padx=2)

        columns = ("type", "path", "status")
        self.tree = ttk.Treeview(self._source_list_frame, columns=columns, show="headings")
        self.tree.heading("type", text="Type")
        self.tree.heading("path", text="Path")
        self.tree.heading("status", text="Status")
        self.tree.column("type", width=80, anchor=tk.W)
        self.tree.column("path", width=520, anchor=tk.W)
        self.tree.column("status", width=80, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection_changed)

        self._tree_context_menu = tk.Menu(self.tree, tearoff=0)
        self._tree_context_menu.add_command(
            label="Delete", command=self._delete_selected_source
        )

    def on_show_source_list(self) -> None:
        if not self._source_list_frame.winfo_ismapped():
            self._source_list_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.refresh_sources()

    def _on_tree_right_click(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self._tree_context_menu.tk_popup(event.x_root, event.y_root)

    def _on_tree_selection_changed(self, event: tk.Event | None = None) -> None:
        self._delete_button.config(state=tk.NORMAL if self.tree.selection() else tk.DISABLED)

    def _delete_selected_source(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        source_id = int(selection[0])
        path = self.tree.item(selection[0], "values")[1]
        if not messagebox.askyesno("Remove source", f"Remove {path} from VethuQ?"):
            return
        try:
            remove_source(self.conn, source_id)
        except SourceNotFoundError as exc:
            messagebox.showerror("Could not remove source", str(exc))
        else:
            self.refresh_sources()

    def _build_status_bar(self) -> None:
        status_bar = ttk.Frame(self)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._status_var = tk.StringVar(value="Idle")
        ttk.Label(status_bar, textvariable=self._status_var, anchor=tk.E).pack(
            side=tk.RIGHT, padx=(4, 8), pady=4
        )

        self._status_progress = ttk.Progressbar(status_bar, mode="indeterminate", length=120)
        self._status_progress.pack(side=tk.RIGHT, pady=4)

    def _set_indexing_status(self, index: int, total: int, path: str) -> None:
        self._status_var.set(f"Indexing ({index}/{total}): {path}")
        self._status_progress.start(10)

    def _set_idle_status(self) -> None:
        self._status_progress.stop()
        self._status_var.set("Idle")

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
            self.tree.insert(
                "",
                tk.END,
                iid=str(source.id),
                values=(source.source_type, source.path, source.status),
            )
        self._on_tree_selection_changed()


def main() -> None:
    multiprocessing.freeze_support()
    window = MainWindow()
    window.mainloop()


if __name__ == "__main__":
    main()
