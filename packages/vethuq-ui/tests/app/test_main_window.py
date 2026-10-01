from unittest.mock import patch

from vethuq_core.index import IndexRunner


class TestMainWindow:
    def test_starts_on_the_search_view(self, window):
        assert window.search.winfo_ismapped()
        assert not window.sources.winfo_ismapped()

    def test_switches_between_search_and_source_list(self, window):
        window.on_show_source_list()
        window.update()
        assert window.sources.winfo_ismapped()
        assert not window.search.winfo_ismapped()

        window.on_show_search()
        window.update()
        assert window.search.winfo_ismapped()
        assert not window.sources.winfo_ismapped()

    def test_showing_the_source_list_refreshes_it(self, window, add_source):
        add_source()
        window.sources.tree.delete(*window.sources.tree.get_children())

        window.on_show_source_list()

        assert len(window.sources.tree.get_children()) == 1

    def test_destroy_asks_the_worker_to_stop_without_waiting(self, tmp_path, monkeypatch):
        from vethuq_ui.app import MainWindow

        monkeypatch.setattr(IndexRunner, "start_run", staticmethod(lambda *a, **k: 0))
        stops = []
        main_window = MainWindow(db_path=tmp_path / "vethuq.db")
        with patch.object(IndexRunner, "signal_stop", lambda **kwargs: stops.append(kwargs)):
            main_window.destroy()

        assert stops == [{"db_path": tmp_path / "vethuq.db"}]

    def test_logs_unhandled_callback_errors_instead_of_printing(self, window, caplog):
        caplog.set_level("ERROR", logger="vethuq_ui")
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            window.report_callback_exception(type(exc), exc, exc.__traceback__)

        assert "Unhandled error in a UI callback" in caplog.text
