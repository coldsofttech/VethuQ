import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from vethuq_ui.widgets import Widgets


class TestWidgets:
    def test_icon_button_kwargs_falls_back_to_a_glyph_without_an_icon(self):
        with patch("vethuq_ui.widgets.get_icon", return_value=None):
            assert Widgets.icon_button_kwargs("stop", "X", "Stop") == {"text": "X\nStop"}
            assert Widgets.icon_button_kwargs("stop", "X", "Go", compound=tk.LEFT) == {
                "text": "X Go"
            }

    def test_icon_button_kwargs_uses_the_icon_when_there_is_one(self):
        with patch("vethuq_ui.widgets.get_icon", return_value="ICON") as get_icon:
            kwargs = Widgets.icon_button_kwargs("search", "X", "Go", compound=tk.LEFT, size=16)

        assert kwargs == {"image": "ICON", "text": "Go", "compound": tk.LEFT}
        get_icon.assert_called_once_with("search", 16)

    def test_flush_left_tree_style_removes_the_indent(self, root):
        Widgets.flush_left_tree_style(root, "Test.Treeview")

        assert int(ttk.Style(root).lookup("Test.Treeview", "indent")) == 0
