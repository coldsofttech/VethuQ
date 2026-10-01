from vethuq_ui.history_pane import HistoryPane


def _seed_runs(conn) -> None:
    conn.execute(
        "INSERT INTO index_runs (target, mode, status, total_files, processed_files, "
        "failed_files, started_at) VALUES (NULL, 'run', 'completed', 4, 4, 1, "
        "'2026-03-05T10:30:00+00:00')"
    )
    conn.execute(
        "INSERT INTO index_runs (target, mode, status, total_files, processed_files, "
        "failed_files, started_at) VALUES ('1', 'restart', 'failed', 2, 1, 1, "
        "'2026-03-06T08:00:00+00:00')"
    )
    conn.commit()


def _history_tree(pane: HistoryPane):
    return next(c for c in pane.winfo_children() if c.winfo_class() == "Treeview")


class TestHistoryPane:
    def test_show_lists_the_runs_for_the_source_and_adds_the_pane(self, window, add_source):
        source_id = add_source()
        _seed_runs(window.conn)

        window.sources.history.show(str(source_id), "/docs")

        tree = _history_tree(window.sources.history)
        values = [tree.item(iid, "values") for iid in tree.get_children()]
        assert len(values) == 2
        assert {v[1] for v in values} == {"Run", "Restart"}
        assert str(window.sources.history) in window.sources.paned.panes()

    def test_hide_removes_the_pane(self, window, add_source):
        source_id = add_source()
        window.sources.history.show(str(source_id), "/docs")

        window.sources.history.hide()

        assert str(window.sources.history) not in window.sources.paned.panes()

    def test_show_twice_does_not_add_the_pane_twice(self, window, add_source):
        source_id = add_source()

        window.sources.history.show(str(source_id), "/docs")
        window.sources.history.show(str(source_id), "/docs")

        assert window.sources.paned.panes().count(str(window.sources.history)) == 1

    def test_show_history_needs_a_selected_source(self, window, add_source):
        add_source()

        window.sources.show_history()

        assert str(window.sources.history) not in window.sources.paned.panes()

    def test_format_timestamp(self):
        assert HistoryPane.format_timestamp("2026-03-05T10:30:00+00:00") == "5 Mar 2026 10:30"
        assert HistoryPane.format_timestamp("not a date") == "not a date"
