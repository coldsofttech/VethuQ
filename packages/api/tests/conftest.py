from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from api_support import HOST, ORIGIN, TOKEN

from vethuq_api import allow_host, create_app


@pytest.fixture(autouse=True)
def _isolated_locations(tmp_path_factory, monkeypatch):
    """Keep the data and backups folders the tests move away from the person's own."""
    from vethuq._paths import _Paths

    root = tmp_path_factory.mktemp("vethuq-data")
    monkeypatch.delenv(_Paths.ENV_VAR, raising=False)
    monkeypatch.setattr(_Paths, "platform_data_root", staticmethod(lambda: root / "default"))
    monkeypatch.setattr(_Paths, "location_file", staticmethod(lambda: root / "config" / "db.json"))


class FakeWindow:
    def __init__(self) -> None:
        self.maximized = False
        self.calls: list[str] = []
        self.picked: str | None = "/chosen/folder"
        self.picked_file: str | None = "/chosen/file.pdf"

    def choose_folder(self, start: str | None = None) -> str | None:
        self.calls.append(f"choose_folder:{start}")
        return self.picked

    def choose_file(self, start: str | None = None) -> str | None:
        self.calls.append(f"choose_file:{start}")
        return self.picked_file

    def reveal(self, path: str) -> None:
        self.calls.append(f"reveal:{path}")

    def minimize(self) -> None:
        self.calls.append("minimize")

    def maximize(self) -> None:
        self.calls.append("maximize")
        self.maximized = True

    def restore(self) -> None:
        self.calls.append("restore")
        self.maximized = False

    def close(self) -> None:
        self.calls.append("close")


class FakeCore:
    def about(self) -> dict[str, object]:
        return {"vethuq": "9.9.9", "python": "3.12.0", "platform": "test", "db_schema": 1}

    def brand(self) -> dict[str, object]:
        return {"name": "Brand", "tagline": "Tag.", "palette": {"light": {}, "dark": {}}}

    def settings(self, section: str) -> list[dict[str, object]]:
        return []

    def update_setting(
        self, section: str, setting_id: str, value: object, options: dict | None = None
    ) -> dict[str, object]:
        return {"id": setting_id, "value": value, "options": options}

    def reset_setting(
        self, section: str, setting_id: str, options: dict | None = None
    ) -> dict[str, object]:
        return {"id": setting_id, "options": options}

    def support_report(self) -> str:
        return "## Support\n"

    one_off = False

    def sources(self):
        return SimpleNamespace(forget=lambda: None)

    def credits(self):
        return SimpleNamespace()

    def stats(self):
        return SimpleNamespace()

    def ocr(self):
        return SimpleNamespace()

    def addons(self):
        return SimpleNamespace()

    def logs(self):
        return SimpleNamespace()

    def github(self):
        return SimpleNamespace()

    def maintenance(self):
        return SimpleNamespace()

    def indexing(self):
        core = self

        class Indexing:
            def one_off_active(self) -> bool:
                return core.one_off

            def stop_for_close(self) -> None:
                core.stopped_for_close = True

        return Indexing()

    stopped_for_close = False

    def catalog(self) -> dict[str, list[dict[str, object]]]:
        return {"add_ons": [{"id": "csv", "name": "vethuq-addon-csv", "version": "0.1.0"}]}


@pytest.fixture
def web_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>VethuQ</title>")
    (dist / "assets" / "app.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("outside the interface")
    return dist


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


@pytest.fixture
def fake_core() -> FakeCore:
    return FakeCore()


@pytest.fixture
def app(web_dist: Path, window: FakeWindow, fake_core: FakeCore):
    application = create_app(
        bootstrap_token=TOKEN,
        web_dist=web_dist,
        window=window,
        host_kind="desktop",
        core=fake_core,
    )
    allow_host(application, HOST)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def signed_in(client):
    """A client that has exchanged the start-up token for a session cookie."""
    response = client.get(f"/?t={TOKEN}", base_url=ORIGIN)
    assert response.status_code == 303
    return client
