"""VethuQ desktop UI: Settings > Sources to add folders/files and manage registered sources."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import sv_ttk
from vethuq_core.db import connect
from vethuq_core.index_runner import (
    AlreadyRunningError,
    IndexRunnerError,
    IndexState,
    StaleLockError,
    is_running,
    read_state,
    request_pause,
    request_resume,
    signal_stop,
    start_run,
)
from vethuq_core.search import search_indexed_content
from vethuq_core.settings import is_gpu_enabled, set_gpu_enabled
from vethuq_core.sources import (
    SourceAlreadyExistsError,
    SourceError,
    SourceNotFoundError,
    add_source,
    list_sources,
    remove_source,
)

from vethuq_ui.icons import get_file_icon, get_icon
from vethuq_ui.tooltip import TreeviewTooltip

_INDEX_POLL_INTERVAL_MS = 5000
_SEARCH_PLACEHOLDER = "Search"
_RESULT_LIST_WIDTH_FRACTION = 0.35
_MAX_DISPLAYED_NAME_CHARS = 35

# Fixed positions within the Sources tree's right-click menu (see
# _build_source_list) - must stay in sync with the order items are added in.
_INDEX_NOW_MENU_INDEX = 0
_RETRY_MENU_INDEX = 1


class MainWindow(tk.Tk):
    def __init__(self, conn: sqlite3.Connection | None = None, db_path: Path | None = None) -> None:
        super().__init__()
        self.conn = conn or connect(db_path)
        self._db_path = db_path

        self.title("VethuQ")
        self.geometry("720x480")
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)
        sv_ttk.set_theme("light")

        self._search_full_names: dict[str, str] = {}
        self._build_menubar()
        self._build_status_bar()
        self._build_search_view()
        self._build_source_list()
        self.on_show_search()
        self._closing = False
        self._launch_or_attach_index()
        self.after(_INDEX_POLL_INTERVAL_MS, self._poll_index_status)

    def _launch_or_attach_index(self) -> None:
        """Start background indexing, unless a run is already in progress.

        A run could already be going if this app instance crashed and
        relaunched, or if `vethuq index run` was started from the CLI - in
        either case we just attach to it via polling rather than starting a
        second one.
        """
        if is_running(self._db_path)[0]:
            return
        try:
            start_run(db_path=self._db_path)
        except (AlreadyRunningError, StaleLockError, SourceNotFoundError):
            # AlreadyRunningError: lost a race with something else starting a
            # run just now - fine, we'll just poll it. StaleLockError: a
            # previous run didn't exit cleanly; leave clearing that to the
            # user (`vethuq index run --force`) rather than doing it silently
            # here. SourceNotFoundError can't actually happen (no target is
            # passed), but is one of start_run's declared errors.
            pass

    def _poll_index_status(self) -> None:
        state = read_state(self._db_path)
        if state is not None and state.status in ("running", "paused"):
            self._set_indexing_status(state)
            self.refresh_sources()
        else:
            self._set_idle_status()
        self._update_index_control_buttons(state)
        if not self._closing:
            self.after(_INDEX_POLL_INTERVAL_MS, self._poll_index_status)

    def destroy(self) -> None:
        # Signal only - don't wait. The worker finishes whatever file it's
        # on and exits by itself (cleaning up its own lock/control files and
        # index_runs row), so the app doesn't need to stay open to see that
        # happen.
        self._closing = True
        try:
            signal_stop(db_path=self._db_path)
        except IndexRunnerError:
            pass
        super().destroy()

    def _build_menubar(self) -> None:
        # A native tk.Menu can't be restyled by sv_ttk (it isn't a ttk
        # widget), so instead of a dropdown menu this is a ribbon-style
        # tabbed toolbar built entirely from themed ttk widgets.
        notebook = ttk.Notebook(self)
        notebook.pack(side=tk.TOP, fill=tk.X)

        home_tab = ttk.Frame(notebook)
        notebook.add(home_tab, text="Home")
        ttk.Button(
            home_tab,
            command=self.on_show_search,
            **self._ribbon_icon_kwargs("search", "\N{LEFT-POINTING MAGNIFYING GLASS}", "Search"),
        ).pack(side=tk.LEFT, padx=6, pady=4)

        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="Settings")

        view_group = self._build_ribbon_group(settings_tab, "View")
        ttk.Button(
            view_group,
            command=self.on_show_source_list,
            **self._ribbon_icon_kwargs("sources", "\N{FILE FOLDER}", "Sources"),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Separator(settings_tab, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6, pady=4
        )

        ocr_group = self._build_ribbon_group(settings_tab, "OCR")
        self._gpu_enabled_var = tk.BooleanVar(value=is_gpu_enabled(self.conn))
        ttk.Checkbutton(
            ocr_group,
            variable=self._gpu_enabled_var,
            command=self._on_toggle_gpu,
            style="Toolbutton",
            **self._ribbon_icon_kwargs("gpu", "\N{HIGH VOLTAGE SIGN}", "GPU"),
        ).pack(side=tk.LEFT, padx=2)

        notebook.select(home_tab)

    @staticmethod
    def _ribbon_icon_kwargs(
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
    def _build_ribbon_group(ribbon: ttk.Frame, caption: str) -> ttk.Frame:
        """A ribbon group: a row for its buttons, with a caption label below."""
        group = ttk.Frame(ribbon)
        group.pack(side=tk.LEFT, padx=4, pady=(4, 0))
        buttons_row = ttk.Frame(group)
        buttons_row.pack(side=tk.TOP)
        ttk.Label(group, text=caption, anchor=tk.CENTER, foreground="grey").pack(
            side=tk.TOP, fill=tk.X, pady=(2, 4)
        )
        return buttons_row

    def _on_toggle_gpu(self) -> None:
        set_gpu_enabled(self.conn, self._gpu_enabled_var.get())

    def _build_search_view(self) -> None:
        self._search_frame = ttk.Frame(self)

        search_bar = ttk.Frame(self._search_frame)
        search_bar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(search_bar, textvariable=self._search_var)
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._search_entry.bind("<Return>", lambda event: self.on_search())
        self._add_search_placeholder()
        ttk.Button(
            search_bar,
            command=self.on_search,
            **self._ribbon_icon_kwargs(
                "search", "\N{LEFT-POINTING MAGNIFYING GLASS}", "Go", compound=tk.LEFT, size=16
            ),
        ).pack(side=tk.LEFT, padx=(4, 0))

        results = ttk.Frame(self._search_frame)
        results.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        list_frame = ttk.Frame(results)
        list_frame.place(relx=0, rely=0, relwidth=_RESULT_LIST_WIDTH_FRACTION, relheight=1)
        content_frame = ttk.Frame(results, relief=tk.SUNKEN, borderwidth=1)
        content_frame.place(
            relx=_RESULT_LIST_WIDTH_FRACTION,
            rely=0,
            relwidth=1 - _RESULT_LIST_WIDTH_FRACTION,
            relheight=1,
        )
        ttk.Label(content_frame, text="Select a result to preview its content.").place(
            relx=0.5, rely=0.5, anchor=tk.CENTER
        )

        self._search_tree = ttk.Treeview(list_frame, columns=("path",), show="tree headings")
        self._search_tree.heading("#0", text="Name")
        self._search_tree.column("#0", width=260, anchor=tk.W, stretch=False)
        self._search_tree.heading("path", text="Path")
        self._search_tree.column("path", width=320, anchor=tk.W, stretch=False)

        hscroll = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self._search_tree.xview)
        self._search_tree.configure(xscrollcommand=hscroll.set)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self._search_tree.pack(fill=tk.BOTH, expand=True)

        TreeviewTooltip(self._search_tree, self._search_full_names.get)

    def _add_search_placeholder(self) -> None:
        entry = self._search_entry

        def clear_placeholder(event: tk.Event | None = None) -> None:
            if self._search_var.get() == _SEARCH_PLACEHOLDER:
                self._search_var.set("")
                entry.config(foreground="black")

        def restore_placeholder(event: tk.Event | None = None) -> None:
            if not self._search_var.get():
                self._search_var.set(_SEARCH_PLACEHOLDER)
                entry.config(foreground="grey")

        entry.bind("<FocusIn>", clear_placeholder)
        entry.bind("<FocusOut>", restore_placeholder)
        restore_placeholder()

    @staticmethod
    def _truncate_name(name: str, max_chars: int = _MAX_DISPLAYED_NAME_CHARS) -> str:
        if len(name) <= max_chars:
            return name
        return name[: max_chars - 1] + "\N{HORIZONTAL ELLIPSIS}"

    def on_search(self) -> None:
        query = self._search_var.get().strip()
        self._search_tree.delete(*self._search_tree.get_children())
        self._search_full_names.clear()
        if not query or query == _SEARCH_PLACEHOLDER:
            return

        seen_files: dict[int, tuple[str, str]] = {}
        for match in search_indexed_content(self.conn, query):
            seen_files.setdefault(match.file_id, (match.file_name, match.file_path))

        for file_id, (file_name, file_path) in seen_files.items():
            iid = str(file_id)
            self._search_full_names[iid] = file_name
            self._search_tree.insert(
                "",
                tk.END,
                iid=iid,
                text=self._truncate_name(file_name),
                image=get_file_icon(file_path),
                values=(file_path,),
            )

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

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        self._pause_resume_button = ttk.Button(
            toolbar, text="Pause", command=self._toggle_pause_resume, state=tk.DISABLED
        )
        self._pause_resume_button.pack(side=tk.LEFT, padx=2)
        self._stop_button = ttk.Button(
            toolbar, text="Stop", command=self._stop_index_run, state=tk.DISABLED
        )
        self._stop_button.pack(side=tk.LEFT, padx=2)

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

        # Fixed layout - indices below must stay in sync with insertion order.
        self._tree_context_menu = tk.Menu(self.tree, tearoff=0)
        self._tree_context_menu.add_command(label="Index Now", command=self._index_selected_source)
        self._tree_context_menu.add_command(
            label="Retry Failed Files", command=self._retry_selected_source
        )
        self._tree_context_menu.add_separator()
        self._tree_context_menu.add_command(label="History...", command=self._show_history)
        self._tree_context_menu.add_separator()
        self._tree_context_menu.add_command(label="Delete", command=self._delete_selected_source)

    def on_show_source_list(self) -> None:
        self._search_frame.pack_forget()
        if not self._source_list_frame.winfo_ismapped():
            self._source_list_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.refresh_sources()

    def on_show_search(self) -> None:
        self._source_list_frame.pack_forget()
        if not self._search_frame.winfo_ismapped():
            self._search_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

    def _on_tree_right_click(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self._update_context_menu_state()
            self._tree_context_menu.tk_popup(event.x_root, event.y_root)

    def _update_context_menu_state(self) -> None:
        # Index Now/Retry Failed Files start a new background run, which
        # can't happen while one is already in progress (Pause/Stop/Resume
        # are global - see the toolbar buttons - since there's a single
        # background worker, not one per source).
        running = is_running(self._db_path)[0]
        self._tree_context_menu.entryconfig(
            _INDEX_NOW_MENU_INDEX, state=tk.DISABLED if running else tk.NORMAL
        )
        self._tree_context_menu.entryconfig(
            _RETRY_MENU_INDEX, state=tk.DISABLED if running else tk.NORMAL
        )

    def _index_selected_source(self) -> None:
        self._start_targeted_run(restart=False)

    def _retry_selected_source(self) -> None:
        self._start_targeted_run(restart=True)

    def _start_targeted_run(self, *, restart: bool) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        try:
            start_run(selection[0], restart=restart, db_path=self._db_path)
        except (AlreadyRunningError, StaleLockError, SourceNotFoundError) as exc:
            messagebox.showerror("Could not start indexing", str(exc))
        else:
            self.refresh_sources()

    def _stop_index_run(self) -> None:
        try:
            signal_stop(db_path=self._db_path)
        except IndexRunnerError as exc:
            messagebox.showerror("Could not stop indexing", str(exc))

    def _toggle_pause_resume(self) -> None:
        state = read_state(self._db_path)
        try:
            if state is not None and state.status == "paused":
                request_resume(db_path=self._db_path)
            else:
                request_pause(db_path=self._db_path)
        except IndexRunnerError as exc:
            messagebox.showerror("Could not update index run", str(exc))

    def _update_index_control_buttons(self, state: IndexState | None) -> None:
        running = state is not None and state.status in ("running", "paused")
        paused = state is not None and state.status == "paused"
        self._pause_resume_button.config(
            text="Resume" if paused else "Pause", state=tk.NORMAL if running else tk.DISABLED
        )
        self._stop_button.config(state=tk.NORMAL if running else tk.DISABLED)

    def _show_history(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        source_id = selection[0]
        path = self.tree.item(selection[0], "values")[1]

        # A run over "all sources" (target IS NULL) would have covered this
        # source too, so it's included alongside runs targeted at just it.
        rows = self.conn.execute(
            "SELECT * FROM index_runs WHERE target = ? OR target IS NULL "
            "ORDER BY started_at DESC LIMIT 20",
            (source_id,),
        ).fetchall()

        dialog = tk.Toplevel(self)
        dialog.title(f"Index History — {path}")
        dialog.geometry("640x320")

        columns = ("started_at", "mode", "target", "status", "progress", "failed")
        tree = ttk.Treeview(dialog, columns=columns, show="headings")
        for column, heading in zip(
            columns, ("Started", "Mode", "Target", "Status", "Progress", "Failed"), strict=False
        ):
            tree.heading(column, text=heading)
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        for row in rows:
            tree.insert(
                "",
                tk.END,
                values=(
                    row["started_at"],
                    row["mode"],
                    row["target"] or "all sources",
                    row["status"],
                    f"{row['processed_files']}/{row['total_files']}",
                    row["failed_files"],
                ),
            )

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

    def _set_indexing_status(self, state: IndexState) -> None:
        if state.status == "paused":
            self._status_var.set(f"Paused ({state.processed_files}/{state.total_files})")
        else:
            current = f": {Path(state.current_file).name}" if state.current_file else ""
            self._status_var.set(f"Indexing ({state.processed_files}/{state.total_files}){current}")
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
            self._launch_or_attach_index()

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
    window = MainWindow()
    window.mainloop()


if __name__ == "__main__":
    main()
