import tkinter as tk
from tkinter import ttk

from vethuq_ui.dialogs import ask_yes_no, show_error, show_warning


def _click_when_open(root: tk.Tk, label: str) -> None:
    """Press the dialog's `label` button as soon as the dialog has opened."""

    def click() -> None:
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                for widget in _walk(child):
                    if isinstance(widget, ttk.Button) and widget.cget("text") == label:
                        widget.invoke()
                        return
        root.after(20, click)

    root.after(20, click)


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


class TestDialogs:
    def test_ask_yes_no_returns_true_on_yes(self, root):
        _click_when_open(root, "Yes")

        assert ask_yes_no(root, "Remove", "Remove it?") is True

    def test_ask_yes_no_returns_false_on_no(self, root):
        _click_when_open(root, "No")

        assert ask_yes_no(root, "Remove", "Remove it?") is False

    def test_error_and_warning_close_on_ok(self, root):
        _click_when_open(root, "OK")
        assert show_error(root, "Oops", "It broke") is None

        _click_when_open(root, "OK")
        assert show_warning(root, "Careful", "Heads up") is None
