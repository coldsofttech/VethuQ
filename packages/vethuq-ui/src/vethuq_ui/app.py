"""VethuQ desktop UI: Settings > Sources to add folders/files and manage registered sources."""

from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

import sv_ttk
from vethuq_core.db import connect, default_db_path
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
from vethuq_core.ocr import get_document_results
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

from vethuq_ui.dialogs import ask_yes_no, show_error, show_warning
from vethuq_ui.icons import get_file_icon, get_icon
from vethuq_ui.tooltip import TreeviewTooltip

_INDEX_POLL_INTERVAL_MS = 5000
_SEARCH_PLACEHOLDER = "Search"
_RESULT_LIST_WIDTH_FRACTION = 0.35
_MAX_DISPLAYED_NAME_CHARS = 35

_LOG_FILENAME = "vethuq-ui.log"
_logger = logging.getLogger("vethuq_ui")


def _configure_logging(db_path: Path | None) -> None:
    """Log to `vethuq-ui.log` next to the database (same dir as the .db,
    lock/state files, etc.) so a UI bug like a silently-failing button
    command shows up somewhere instead of only in a console no one is
    watching (Tk swallows exceptions raised inside `command=` callbacks).
    """
    if _logger.handlers:
        return
    log_path = (db_path or default_db_path()).parent / _LOG_FILENAME
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)


class MainWindow(tk.Tk):
    def __init__(self, conn: sqlite3.Connection | None = None, db_path: Path | None = None) -> None:
        _configure_logging(db_path)
        super().__init__()
        self.conn = conn or connect(db_path)
        self._db_path = db_path
        _logger.info("VethuQ UI started")

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

    def report_callback_exception(self, exc: type, val: BaseException, tb: Any) -> None:
        # Tk's default just prints to stderr, invisible once the app is
        # launched as a GUI (no attached console) - log it instead, e.g. an
        # exception raised inside a button's command silently doing nothing.
        _logger.error("Unhandled error in a UI callback", exc_info=(exc, val, tb))

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

        ttk.Separator(home_tab, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        sources_group = self._build_ribbon_group(home_tab, "Sources")
        ttk.Button(
            sources_group,
            command=self.on_add_folder,
            **self._ribbon_icon_kwargs("folder", "\N{FILE FOLDER}", "Folder"),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            sources_group,
            command=self.on_add_file,
            **self._ribbon_icon_kwargs("file", "\N{PAGE FACING UP}", "File"),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            sources_group,
            command=self.on_show_source_list,
            **self._ribbon_icon_kwargs("list", "\N{CARD INDEX DIVIDERS}", "List"),
        ).pack(side=tk.LEFT, padx=2)
        self._pause_resume_button = ttk.Button(
            sources_group,
            command=self._toggle_pause_resume,
            state=tk.DISABLED,
            **self._ribbon_icon_kwargs("pause", "\N{DOUBLE VERTICAL BAR}", "Pause"),
        )
        self._pause_resume_button.pack(side=tk.LEFT, padx=2)
        self._stop_button = ttk.Button(
            sources_group,
            command=self._stop_index_run,
            state=tk.DISABLED,
            **self._ribbon_icon_kwargs("stop", "\N{BLACK SQUARE FOR STOP}", "Stop"),
        )
        self._stop_button.pack(side=tk.LEFT, padx=2)
        self._delete_button = ttk.Button(
            sources_group,
            command=self._delete_selected_source,
            **self._ribbon_icon_kwargs("delete", "\N{WASTEBASKET}", "Delete"),
        )

        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="Settings")

        ocr_group = self._build_ribbon_group(settings_tab, "GPU")
        self._gpu_enabled_var = tk.BooleanVar(value=is_gpu_enabled(self.conn))
        self._gpu_button = ttk.Checkbutton(
            ocr_group,
            variable=self._gpu_enabled_var,
            command=self._on_toggle_gpu,
            style="Toolbutton",
            **self._ribbon_icon_kwargs(self._gpu_icon_name(), "\N{HIGH VOLTAGE SIGN}", ""),
        )
        self._gpu_button.pack(side=tk.LEFT, padx=2)

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

    def _flush_left_tree_style(self, style_name: str) -> None:
        """A Treeview style with no indicator/indent, so a row's own image
        (e.g. a file-type or source-type icon) sits flush against the left edge."""
        style = ttk.Style(self)
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

    def _gpu_icon_name(self) -> str:
        return "gpu" if self._gpu_enabled_var.get() else "gpu-disable"

    def _on_toggle_gpu(self) -> None:
        set_gpu_enabled(self.conn, self._gpu_enabled_var.get())
        icon = get_icon(self._gpu_icon_name())
        if icon is not None:
            self._gpu_button.configure(image=icon)

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

        self._flush_left_tree_style("Search.Treeview")
        self._search_tree = ttk.Treeview(
            list_frame, columns=("path",), show="tree headings", style="Search.Treeview"
        )
        self._search_tree.heading("#0", text="Name")
        self._search_tree.column("#0", width=260, minwidth=80, anchor=tk.W, stretch=False)
        self._search_tree.heading("path", text="Path")
        self._search_tree.column("path", width=320, minwidth=80, anchor=tk.W, stretch=True)

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
            return f" {name}"
        return f" {name[: max_chars - 1]}\N{HORIZONTAL ELLIPSIS}"

    def on_search(self) -> None:
        query = self._search_var.get().strip()
        self._search_tree.delete(*self._search_tree.get_children())
        self._search_full_names.clear()
        if not query or query == _SEARCH_PLACEHOLDER:
            return

        seen_files: dict[int, tuple[str, str, bool]] = {}
        for match in search_indexed_content(self.conn, query):
            is_duplicate = match.duplicate_of_path is not None
            seen_files.setdefault(match.file_id, (match.file_name, match.file_path, is_duplicate))

        for file_id, (file_name, file_path, is_duplicate) in seen_files.items():
            iid = str(file_id)
            display_name = f"{file_name} (duplicate)" if is_duplicate else file_name
            if len(display_name) > _MAX_DISPLAYED_NAME_CHARS:
                self._search_full_names[iid] = display_name
            self._search_tree.insert(
                "",
                tk.END,
                iid=iid,
                text=self._truncate_name(display_name),
                image=get_file_icon(file_path),
                values=(file_path,),
            )

    def _build_source_list(self) -> None:
        self._source_list_frame = ttk.Frame(self)
        self._sources_paned = ttk.Panedwindow(self._source_list_frame, orient=tk.HORIZONTAL)
        self._sources_paned.pack(fill=tk.BOTH, expand=True)
        self._sources_list_pane = ttk.Frame(self._sources_paned)
        self._sources_history_pane = ttk.Frame(self._sources_paned, relief=tk.SUNKEN, borderwidth=1)
        self._sources_paned.add(self._sources_list_pane, weight=1)

        self._flush_left_tree_style("Sources.Treeview")
        columns = ("path", "status", "progress")
        self.tree = ttk.Treeview(
            self._sources_list_pane, columns=columns, show="tree headings", style="Sources.Treeview"
        )
        self.tree.heading("#0", text="Type")
        self.tree.heading("path", text="Path")
        self.tree.heading("status", text="Status")
        self.tree.heading("progress", text="Progress")
        self.tree.column("#0", width=90, minwidth=90, anchor=tk.W, stretch=False)
        self.tree.column("path", width=440, anchor=tk.W)
        self.tree.column("status", width=80, anchor=tk.W)
        self.tree.column("progress", width=160, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection_changed)
        TreeviewTooltip(self.tree, self._source_tooltip_text)

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
            self._show_context_menu(event.x_root, event.y_root)

    def _show_context_menu(self, x: int, y: int) -> None:
        # A native tk.Menu can't be restyled by sv_ttk (it isn't a ttk
        # widget, and Windows draws it natively regardless of color options),
        # so this is a themed popup built from real ttk widgets instead.
        running = is_running(self._db_path)[0]
        menu = tk.Toplevel(self)
        menu.wm_overrideredirect(True)
        menu.wm_attributes("-topmost", True)
        frame = ttk.Frame(menu, relief=tk.SOLID, borderwidth=1, padding=2)
        frame.pack()
        ttk.Style(self).configure("ContextMenu.Toolbutton", anchor=tk.W, padding=(6, 1))

        def close() -> None:
            self.unbind_all("<Button-1>")
            menu.destroy()

        def add_item(label: str, command: Any, *, disabled: bool = False) -> None:
            def run() -> None:
                close()
                command()

            button = ttk.Button(frame, text=label, command=run, style="ContextMenu.Toolbutton")
            if disabled:
                button.state(["disabled"])
            button.pack(fill=tk.X, padx=2, pady=1)

        # Index Now/Retry Failed Files start a new background run, which
        # can't happen while one is already in progress (Pause/Stop/Resume
        # are global - see the toolbar buttons - since there's a single
        # background worker, not one per source).
        add_item("Index Now", self._index_selected_source, disabled=running)
        add_item("Retry Failed Files", self._retry_selected_source, disabled=running)
        ttk.Separator(frame).pack(fill=tk.X, pady=2)
        add_item("History...", self._show_history)
        ttk.Separator(frame).pack(fill=tk.X, pady=2)
        add_item("Delete", self._delete_selected_source)

        menu.update_idletasks()
        menu.geometry(f"+{x}+{y}")

        # A raw <FocusOut> on `menu` would fire (and destroy it) the instant
        # one of its own buttons takes focus on click, before that button's
        # command ever runs - so dismiss on an app-wide click that lands
        # outside the popup instead, ignoring clicks on the popup itself.
        def dismiss_if_outside(event: tk.Event) -> None:
            widget_path = str(event.widget)
            menu_path = str(menu)
            if widget_path != menu_path and not widget_path.startswith(menu_path + "."):
                close()

        self.bind_all("<Button-1>", dismiss_if_outside, add="+")

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
            show_error(self, "Could not start indexing", str(exc))
        else:
            self.refresh_sources()

    def _stop_index_run(self) -> None:
        try:
            signal_stop(db_path=self._db_path)
        except IndexRunnerError as exc:
            show_error(self, "Could not stop indexing", str(exc))

    def _toggle_pause_resume(self) -> None:
        state = read_state(self._db_path)
        try:
            if state is not None and state.status == "paused":
                request_resume(db_path=self._db_path)
            else:
                request_pause(db_path=self._db_path)
        except IndexRunnerError as exc:
            show_error(self, "Could not update index run", str(exc))

    def _update_index_control_buttons(self, state: IndexState | None) -> None:
        running = state is not None and state.status in ("running", "paused")
        paused = state is not None and state.status == "paused"
        icon = get_icon("resume" if paused else "pause")
        if icon is not None:
            self._pause_resume_button.config(image=icon)
        self._pause_resume_button.config(
            text="Resume" if paused else "Pause",
            state=tk.NORMAL if running else tk.DISABLED,
        )
        self._stop_button.config(state=tk.NORMAL if running else tk.DISABLED)

    def _show_history(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        source_id = selection[0]
        path = self.tree.item(selection[0], "values")[0]

        # A run over "all sources" (target IS NULL) would have covered this
        # source too, so it's included alongside runs targeted at just it.
        rows = self.conn.execute(
            "SELECT * FROM index_runs WHERE target = ? OR target IS NULL "
            "ORDER BY started_at DESC LIMIT 20",
            (source_id,),
        ).fetchall()

        for child in self._sources_history_pane.winfo_children():
            child.destroy()
        header = ttk.Frame(self._sources_history_pane)
        header.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(header, text=f"Index History — {path}").pack(side=tk.LEFT)
        ttk.Button(header, text="Close", command=self._hide_history).pack(side=tk.RIGHT)

        columns = ("started_at", "mode", "target", "status", "progress", "failed")
        tree = ttk.Treeview(self._sources_history_pane, columns=columns, show="headings")
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

        hscroll = ttk.Scrollbar(
            self._sources_history_pane, orient=tk.HORIZONTAL, command=tree.xview
        )
        tree.configure(xscrollcommand=hscroll.set)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X, padx=8)
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        for row in rows:
            tree.insert(
                "",
                tk.END,
                values=(
                    self._format_history_timestamp(row["started_at"]),
                    row["mode"].capitalize(),
                    row["target"] if row["target"] is not None else "All sources",
                    row["status"].capitalize(),
                    f"{row['processed_files']}/{row['total_files']}",
                    row["failed_files"],
                ),
            )

        if str(self._sources_history_pane) not in self._sources_paned.panes():
            self._sources_paned.add(self._sources_history_pane, weight=1)
            self._sources_paned.update_idletasks()
            self._sources_paned.sashpos(0, self._sources_paned.winfo_width() // 2)

    @staticmethod
    def _format_history_timestamp(value: str) -> str:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value
        return f"{dt.day} {dt.strftime('%b %Y %H:%M')}"

    def _hide_history(self) -> None:
        if str(self._sources_history_pane) in self._sources_paned.panes():
            self._sources_paned.forget(self._sources_history_pane)

    def _on_tree_selection_changed(self, event: tk.Event | None = None) -> None:
        if self.tree.selection():
            if not self._delete_button.winfo_ismapped():
                self._delete_button.pack(side=tk.LEFT, padx=2)
        else:
            self._delete_button.pack_forget()

    def _delete_selected_source(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        source_id = int(selection[0])
        path = self.tree.item(selection[0], "values")[0]
        if not ask_yes_no(self, "Remove source", f"Remove {path} from VethuQ?"):
            return
        try:
            remove_source(self.conn, source_id)
        except SourceNotFoundError as exc:
            show_error(self, "Could not remove source", str(exc))
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
            show_warning(self, "Already added", f"{path} is already registered.")
        except SourceError as exc:
            show_error(self, "Could not add source", str(exc))
        else:
            self.refresh_sources()
            self._launch_or_attach_index()

    def refresh_sources(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for source in list_sources(self.conn):
            results = get_document_results(self.conn, source.id)
            done = sum(1 for result in results if result.status == "indexed")
            noun = "file" if len(results) == 1 else "files"
            icon_kwargs: dict[str, Any] = {}
            icon = get_icon(source.source_type, 16)
            if icon is not None:
                icon_kwargs["image"] = icon
            self.tree.insert(
                "",
                tk.END,
                iid=str(source.id),
                text=f" {source.source_type.capitalize()}",
                values=(
                    source.path,
                    source.status.capitalize(),
                    f"{done}/{len(results)} {noun} processed",
                ),
                **icon_kwargs,
            )
        self._on_tree_selection_changed()

    def _source_tooltip_text(self, iid: str) -> str | None:
        path = self.tree.set(iid, "path")
        font = tkfont.nametofont("TkDefaultFont")
        column_width = self.tree.column("path", "width")
        return path if font.measure(path) > column_width - 10 else None


def main() -> None:
    window = MainWindow()
    window.mainloop()


if __name__ == "__main__":
    main()
