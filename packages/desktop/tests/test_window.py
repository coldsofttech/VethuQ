from __future__ import annotations

from vethuq_desktop.window import SimulatedWindowController, WebviewWindowController


class _Event(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self


class _Events:
    def __init__(self) -> None:
        self.maximized = _Event()
        self.restored = _Event()
        self.closing = _Event()
        self.loaded = _Event()


class _FakeWindow:
    def __init__(self) -> None:
        self.events = _Events()
        self.calls: list[str] = []

    def minimize(self):
        self.calls.append("minimize")

    def maximize(self):
        self.calls.append("maximize")

    def restore(self):
        self.calls.append("restore")

    def destroy(self):
        self.calls.append("destroy")


def test_webview_controller_drives_the_window_and_follows_its_events():
    window = _FakeWindow()
    controller = WebviewWindowController()
    controller.attach(window)

    controller.maximize()
    assert controller.maximized
    controller.restore()
    assert not controller.maximized
    controller.minimize()
    controller.close()
    assert window.calls == ["maximize", "restore", "minimize", "destroy"]

    # The user maximises with the keyboard or by snapping: the window reports it.
    for handler in window.events.maximized:
        handler()
    assert controller.maximized
    for handler in window.events.restored:
        handler()
    assert not controller.maximized


def test_simulated_controller_tracks_state_and_signals_close():
    controller = SimulatedWindowController()
    controller.maximize()
    assert controller.maximized
    controller.restore()
    assert not controller.maximized
    assert not controller.closed.is_set()
    controller.close()
    assert controller.closed.is_set()


class _PickerWindow(_FakeWindow):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer
        self.asked: list[tuple[object, str]] = []

    def create_file_dialog(self, kind, directory="", **extra):
        self.asked.append((kind, directory))
        return self.answer


def _fake_webview(monkeypatch, **attributes):
    import sys
    import types

    module = types.ModuleType("webview")
    for name, value in attributes.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, "webview", module)


def test_choose_folder_shows_the_system_folder_picker_at_the_start_folder(monkeypatch):
    import types

    folder = object()
    _fake_webview(monkeypatch, FileDialog=types.SimpleNamespace(FOLDER=folder))
    window = _PickerWindow(["D:/Chosen"])
    controller = WebviewWindowController()
    controller.attach(window)

    assert controller.choose_folder("C:/Start") == "D:/Chosen"
    assert window.asked == [(folder, "C:/Start")]


def test_choose_folder_returns_none_when_cancelled(monkeypatch):
    import types

    _fake_webview(monkeypatch, FileDialog=types.SimpleNamespace(FOLDER=object()))
    controller = WebviewWindowController()
    controller.attach(_PickerWindow(None))
    assert controller.choose_folder() is None


def test_choose_folder_works_with_an_older_pywebview(monkeypatch):
    legacy = object()
    _fake_webview(monkeypatch, FOLDER_DIALOG=legacy)
    window = _PickerWindow(("E:/Old",))
    controller = WebviewWindowController()
    controller.attach(window)
    assert controller.choose_folder() == "E:/Old"
    assert window.asked == [(legacy, "")]


class TestClosing:
    def attached(self, guard):
        window = _FakeWindow()
        window.events.closing = _Event()
        window.events.loaded = _Event()
        window.scripts = []
        window.evaluate_js = window.scripts.append
        controller = WebviewWindowController()
        controller.close_guard = guard
        controller.attach(window)
        return controller, window

    def test_closing_goes_ahead_when_nothing_would_stop(self):
        controller, window = self.attached(lambda: False)
        assert window.events.closing[0]() is True
        assert window.scripts == []

    def test_closing_is_held_back_and_the_interface_told_while_a_run_of_ours_goes(self):
        controller, window = self.attached(lambda: True)
        assert window.events.closing[0]() is False
        assert window.scripts and "vethuq:close-blocked" in window.scripts[0]

    def test_a_confirmed_close_is_not_held_back_again(self):
        controller, window = self.attached(lambda: True)
        controller.close()
        assert window.events.closing[0]() is True
        assert window.calls[-1] == "destroy"

    def test_without_a_guard_closing_goes_ahead(self):
        controller, window = self.attached(None)
        assert window.events.closing[0]() is True


class TestDroppedFiles:
    def test_dropped_paths_reach_the_interface(self):
        window = _FakeWindow()
        window.events.closing = _Event()
        window.events.loaded = _Event()
        sent = []
        window.evaluate_js = sent.append
        controller = WebviewWindowController()
        controller.attach(window)
        controller._on_drop(
            {
                "dataTransfer": {
                    "files": [{"pywebviewFullPath": "C:/a.pdf"}, {"name": "no path"}],
                }
            }
        )
        assert "vethuq:drop" in sent[0] and "C:/a.pdf" in sent[0] and "no path" not in sent[0]

    def test_the_drop_handlers_are_installed_once_the_page_has_loaded(self, monkeypatch):
        import sys
        import types

        class Handler:
            def __init__(self, callback, prevent_default, stop_propagation):
                self.callback = callback

        dom = types.ModuleType("webview.dom")
        dom.DOMEventHandler = Handler
        monkeypatch.setitem(sys.modules, "webview", types.ModuleType("webview"))
        monkeypatch.setitem(sys.modules, "webview.dom", dom)

        window = _FakeWindow()
        window.events.closing = _Event()
        window.events.loaded = _Event()
        document = types.SimpleNamespace(
            events=types.SimpleNamespace(drop=_Event(), dragover=_Event())
        )
        window.dom = types.SimpleNamespace(document=document)
        controller = WebviewWindowController()
        controller.attach(window)
        window.events.loaded[0]()
        window.events.loaded[0]()  # a second load must not add a second handler
        assert len(document.events.drop) == 1 and len(document.events.dragover) == 1


class TestPickers:
    def test_choose_file_asks_for_one_file(self, monkeypatch):
        import types

        picked = object()
        _fake_webview(monkeypatch, FileDialog=types.SimpleNamespace(OPEN=picked, FOLDER=object()))
        window = _PickerWindow(["D:/a.pdf"])
        original = window.create_file_dialog
        options = {}

        def record(kind, directory="", **extra):
            options.update(extra)
            return original(kind, directory)

        window.create_file_dialog = record
        controller = WebviewWindowController()
        controller.attach(window)
        assert controller.choose_file("C:/start") == "D:/a.pdf"
        assert options == {"allow_multiple": False}
        assert window.asked == [(picked, "C:/start")]

    def test_reveal_shows_the_file_in_the_system_file_manager(self, monkeypatch, tmp_path):
        import subprocess
        import sys

        started = []
        monkeypatch.setattr(subprocess, "Popen", lambda command: started.append(command))
        file = tmp_path / "a.txt"
        file.write_text("x")
        WebviewWindowController().reveal(str(file))
        command = started[0]
        if sys.platform == "win32":
            assert command[:2] == ["explorer", "/select,"]
        else:
            assert command == ["xdg-open", str(tmp_path)]
