import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from vethuq_core.index import IndexRunner
from vethuq_ui import source_list


def _rows(view):
    return [list(view.tree.item(iid, "values")) for iid in view.tree.get_children()]


class TestSourceListView:
    def test_adding_a_source_lists_it_and_triggers_indexing(self, window, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        launches = []
        with patch.object(window.index_controls, "launch_or_attach", lambda: launches.append(1)):
            window.sources.add_source(str(folder))

        assert _rows(window.sources) == [[str(folder.resolve()), "Pending", "0/0 files processed"]]
        assert launches == [1]

    def test_adding_a_duplicate_warns_and_does_not_list_it_twice(self, window, add_source):
        add_source()
        folder = window.conn.execute("SELECT path FROM sources").fetchone()["path"]
        with patch.object(source_list, "show_warning") as warning:
            window.sources.add_source(folder)

        warning.assert_called_once()
        assert len(window.sources.tree.get_children()) == 1

    def test_adding_a_missing_path_shows_an_error(self, window, tmp_path):
        with patch.object(source_list, "show_error") as error:
            window.sources.add_source(str(tmp_path / "missing"))

        error.assert_called_once()
        assert window.sources.tree.get_children() == ()

    def test_refresh_shows_how_many_files_are_processed(
        self, window, add_source, seed_document, tmp_path
    ):
        source_id = add_source()
        seed_document(window.conn, source_id, tmp_path / "docs" / "a.pdf")
        seed_document(window.conn, source_id, tmp_path / "docs" / "b.pdf", status="error")

        window.sources.refresh()

        assert _rows(window.sources)[0][2] == "1/2 files processed"

    def test_selection_toggles_the_ribbons_delete_button(self, window, add_source):
        add_source()
        first = window.sources.tree.get_children()[0]
        window.on_show_source_list()
        window.update()
        assert not window.ribbon.delete_button.winfo_ismapped()

        window.sources.tree.selection_set(first)
        window.update()
        assert window.ribbon.delete_button.winfo_ismapped()

        window.sources.tree.selection_remove(first)
        window.update()
        assert not window.ribbon.delete_button.winfo_ismapped()

    def test_delete_removes_the_selected_source_when_confirmed(self, window, add_source):
        add_source()
        window.sources.tree.selection_set(window.sources.tree.get_children()[0])

        with patch.object(source_list, "ask_yes_no", return_value=True):
            window.sources.delete_selected()

        assert window.sources.tree.get_children() == ()
        assert window.conn.execute("SELECT is_active FROM sources").fetchone()["is_active"] == 0

    def test_delete_keeps_the_source_when_declined(self, window, add_source):
        add_source()
        window.sources.tree.selection_set(window.sources.tree.get_children()[0])

        with patch.object(source_list, "ask_yes_no", return_value=False):
            window.sources.delete_selected()

        assert len(window.sources.tree.get_children()) == 1

    def test_delete_without_a_selection_does_nothing(self, window):
        with patch.object(source_list, "ask_yes_no") as ask:
            window.sources.delete_selected()

        ask.assert_not_called()

    def test_tooltip_text_only_for_paths_wider_than_their_column(self, window, add_source):
        add_source()
        iid = window.sources.tree.get_children()[0]
        window.sources.tree.column("path", width=2000)
        assert window.sources._tooltip_text(iid) is None

        window.sources.tree.column("path", width=20)
        assert window.sources._tooltip_text(iid) == window.sources.tree.set(iid, "path")


class TestSourceContextMenu:
    @staticmethod
    def _menu_buttons(view) -> dict[str, str]:
        menu = next(c for c in view.winfo_children() if isinstance(c, tk.Toplevel))
        buttons: dict[str, str] = {}

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button):
                    buttons[str(child.cget("text"))] = (
                        "disabled" if child.instate(["disabled"]) else "normal"
                    )
                walk(child)

        walk(menu)
        return buttons

    def test_offers_every_action_while_idle(self, window, add_source):
        add_source()
        with patch.object(IndexRunner, "is_running", return_value=(False, None)):
            window.sources.show_context_menu(5, 5)
        window.update()

        assert self._menu_buttons(window.sources) == {
            "Index Now": "normal",
            "Retry Failed Files": "normal",
            "History...": "normal",
            "Delete": "normal",
        }

    def test_cannot_start_a_run_while_one_is_in_progress(self, window, add_source):
        add_source()
        with patch.object(IndexRunner, "is_running", return_value=(True, 123)):
            window.sources.show_context_menu(5, 5)
        window.update()

        buttons = self._menu_buttons(window.sources)
        assert buttons["Index Now"] == "disabled"
        assert buttons["Retry Failed Files"] == "disabled"
        assert buttons["History..."] == "normal"

    def test_index_now_and_retry_start_a_targeted_run(self, window, add_source):
        add_source()
        first = window.sources.tree.get_children()[0]
        calls = []
        with patch.object(
            window.index_controls,
            "start_targeted_run",
            lambda source_id, *, restart: calls.append((source_id, restart)),
        ):
            window.sources.tree.selection_set(first)
            window.sources._index_selected(restart=False)
            window.sources._index_selected(restart=True)

        assert calls == [(first, False), (first, True)]
