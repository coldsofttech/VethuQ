"""The source list view: registered sources, their progress, and per-source actions."""

from __future__ import annotations

import sqlite3
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from vethuq_core.index import IndexRunner
from vethuq_core.source import SourceAlreadyExistsError, SourceError, SourceNotFoundError, Sources

from vethuq_ui.dialogs import ask_yes_no, show_error, show_warning
from vethuq_ui.history_pane import HistoryPane
from vethuq_ui.icons import get_icon
from vethuq_ui.tooltip import TreeviewTooltip
from vethuq_ui.widgets import Widgets


class SourceListView(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        conn: sqlite3.Connection,
        db_path: Path | None,
        *,
        on_index: Callable[[str, bool], None],
        on_source_added: Callable[[], None],
        on_selection_changed: Callable[[bool], None],
    ) -> None:
        """`on_index(source_id, restart)` starts a run for one source; `on_source_added`
        fires after a source is registered; `on_selection_changed(has_selection)` fires
        whenever the selection (or the list) changes."""
        super().__init__(parent)
        self._conn = conn
        self._db_path = db_path
        self._on_index = on_index
        self._on_source_added = on_source_added
        self._on_selection_changed = on_selection_changed

        self.paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)
        self._list_pane = ttk.Frame(self.paned)
        self.history = HistoryPane(self.paned, conn)
        self.paned.add(self._list_pane, weight=1)

        Widgets.flush_left_tree_style(self, "Sources.Treeview")
        columns = ("path", "status", "progress")
        self.tree = ttk.Treeview(
            self._list_pane, columns=columns, show="tree headings", style="Sources.Treeview"
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
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_selection_changed)
        TreeviewTooltip(self.tree, self._tooltip_text)

    # -- adding / removing sources

    def on_add_folder(self) -> None:
        path = filedialog.askdirectory(title="Select a folder to add to VethuQ")
        if path:
            self.add_source(path)

    def on_add_file(self) -> None:
        paths = filedialog.askopenfilenames(title="Select file(s) to add to VethuQ")
        for path in paths:
            self.add_source(path)

    def add_source(self, path: str) -> None:
        try:
            Sources.add(self._conn, path)
        except SourceAlreadyExistsError:
            show_warning(self.winfo_toplevel(), "Already added", f"{path} is already registered.")
        except SourceError as exc:
            show_error(self.winfo_toplevel(), "Could not add source", str(exc))
        else:
            self.refresh()
            self._on_source_added()

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        source_id = int(selection[0])
        path = self.tree.item(selection[0], "values")[0]
        if not ask_yes_no(self.winfo_toplevel(), "Remove source", f"Remove {path} from VethuQ?"):
            return
        try:
            Sources.remove(self._conn, source_id)
        except SourceNotFoundError as exc:
            show_error(self.winfo_toplevel(), "Could not remove source", str(exc))
        else:
            self.refresh()

    # -- the list itself

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for source in Sources.list_all(self._conn):
            done, total = Sources.progress(self._conn, source.id)
            noun = "file" if total == 1 else "files"
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
                    f"{done}/{total} {noun} processed",
                ),
                **icon_kwargs,
            )
        self.on_selection_changed()

    def on_selection_changed(self, event: tk.Event | None = None) -> None:
        self._on_selection_changed(bool(self.tree.selection()))

    def _tooltip_text(self, iid: str) -> str | None:
        path = self.tree.set(iid, "path")
        font = tkfont.nametofont("TkDefaultFont")
        column_width = self.tree.column("path", "width")
        return path if font.measure(path) > column_width - 10 else None

    def show_history(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.history.show(selection[0], self.tree.item(selection[0], "values")[0])

    def hide_history(self) -> None:
        self.history.hide()

    def _index_selected(self, *, restart: bool) -> None:
        selection = self.tree.selection()
        if selection:
            self._on_index(selection[0], restart)

    # -- context menu

    def _on_right_click(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.show_context_menu(event.x_root, event.y_root)

    def show_context_menu(self, x: int, y: int) -> None:
        # A native tk.Menu can't be restyled by sv_ttk (it isn't a ttk
        # widget, and Windows draws it natively regardless of color options),
        # so this is a themed popup built from real ttk widgets instead.
        running = IndexRunner.is_running(self._db_path)[0]
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
        add_item("Index Now", lambda: self._index_selected(restart=False), disabled=running)
        add_item("Retry Failed Files", lambda: self._index_selected(restart=True), disabled=running)
        ttk.Separator(frame).pack(fill=tk.X, pady=2)
        add_item("History...", self.show_history)
        ttk.Separator(frame).pack(fill=tk.X, pady=2)
        add_item("Delete", self.delete_selected)

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
