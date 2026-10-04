"""The search view: a query bar and a list of the files whose content matches."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from vethuq_core.search import Search
from vethuq_core.storage import Storage

from vethuq_ui.fonts import TeluguFont
from vethuq_ui.icons import Icons
from vethuq_ui.tooltip import TreeviewTooltip
from vethuq_ui.widgets import Widgets


class SearchView(ttk.Frame):
    PLACEHOLDER = "Search"
    RESULT_LIST_WIDTH_FRACTION = 0.35
    MAX_DISPLAYED_NAME_CHARS = 35

    def __init__(self, parent: tk.Misc, storage: Storage) -> None:
        super().__init__(parent)
        self._storage = storage
        self.full_names: dict[str, str] = {}

        search_bar = ttk.Frame(self)
        search_bar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        self.var = tk.StringVar()
        self.entry = ttk.Entry(search_bar, textvariable=self.var)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # The entry keeps its font for English and switches to a Telugu-capable one while it holds
        # Telugu, so a query can be typed or pasted in Telugu script.
        self._entry_font = self.entry.cget("font")
        self.var.trace_add("write", lambda *_: self._sync_entry_font())
        self.entry.bind("<Return>", lambda event: self.on_search())
        self._add_placeholder()
        ttk.Button(
            search_bar,
            command=self.on_search,
            **Widgets.icon_button_kwargs(
                "search", "\N{LEFT-POINTING MAGNIFYING GLASS}", "Go", compound=tk.LEFT, size=16
            ),
        ).pack(side=tk.LEFT, padx=(4, 0))

        results = ttk.Frame(self)
        results.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        list_frame = ttk.Frame(results)
        list_frame.place(relx=0, rely=0, relwidth=self.RESULT_LIST_WIDTH_FRACTION, relheight=1)
        content_frame = ttk.Frame(results, relief=tk.SUNKEN, borderwidth=1)
        content_frame.place(
            relx=self.RESULT_LIST_WIDTH_FRACTION,
            rely=0,
            relwidth=1 - self.RESULT_LIST_WIDTH_FRACTION,
            relheight=1,
        )
        ttk.Label(content_frame, text="Select a result to preview its content.").place(
            relx=0.5, rely=0.5, anchor=tk.CENTER
        )

        Widgets.flush_left_tree_style(self, "Search.Treeview")
        self.tree = ttk.Treeview(
            list_frame, columns=("path",), show="tree headings", style="Search.Treeview"
        )
        self.tree.heading("#0", text="Name")
        self.tree.column("#0", width=260, minwidth=80, anchor=tk.W, stretch=False)
        self.tree.heading("path", text="Path")
        self.tree.column("path", width=320, minwidth=80, anchor=tk.W, stretch=True)

        hscroll = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(xscrollcommand=hscroll.set)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(fill=tk.BOTH, expand=True)

        TreeviewTooltip(self.tree, self.full_names.get)

    def _sync_entry_font(self) -> None:
        telugu = TeluguFont.font_for(self) if TeluguFont.needs_font(self.var.get()) else None
        self.entry.configure(font=telugu or self._entry_font)

    def _add_placeholder(self) -> None:
        entry = self.entry

        def clear_placeholder(event: tk.Event | None = None) -> None:
            if self.var.get() == self.PLACEHOLDER:
                self.var.set("")
                entry.config(foreground="black")

        def restore_placeholder(event: tk.Event | None = None) -> None:
            if not self.var.get():
                self.var.set(self.PLACEHOLDER)
                entry.config(foreground="grey")

        entry.bind("<FocusIn>", clear_placeholder)
        entry.bind("<FocusOut>", restore_placeholder)
        restore_placeholder()

    @staticmethod
    def truncate_name(name: str, max_chars: int = MAX_DISPLAYED_NAME_CHARS) -> str:
        if len(name) <= max_chars:
            return f" {name}"
        return f" {name[: max_chars - 1]}\N{HORIZONTAL ELLIPSIS}"

    def on_search(self) -> None:
        query = self.var.get().strip()
        self.tree.delete(*self.tree.get_children())
        self.full_names.clear()
        if not query or query == self.PLACEHOLDER:
            return

        for file in Search.files(self._storage, query):
            iid = str(file.file_id)
            display_name = f"{file.file_name} (duplicate)" if file.is_duplicate else file.file_name
            if len(display_name) > self.MAX_DISPLAYED_NAME_CHARS:
                self.full_names[iid] = display_name
            telugu = TeluguFont.font_for(self) if TeluguFont.needs_font(display_name) else None
            if telugu is not None:
                self.tree.tag_configure("telugu", font=telugu)
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                text=self.truncate_name(display_name),
                image=Icons.for_file(file.file_path),
                values=(file.file_path,),
                tags=("telugu",) if telugu is not None else (),
            )
