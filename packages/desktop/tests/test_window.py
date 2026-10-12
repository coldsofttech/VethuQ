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

    def create_file_dialog(self, kind, directory=""):
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
