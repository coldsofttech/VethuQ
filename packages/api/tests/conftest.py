from __future__ import annotations

from pathlib import Path

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

    def choose_folder(self, start: str | None = None) -> str | None:
        self.calls.append(f"choose_folder:{start}")
        return self.picked

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
def app(web_dist: Path, window: FakeWindow):
    application = create_app(
        bootstrap_token=TOKEN,
        web_dist=web_dist,
        window=window,
        host_kind="desktop",
        core=FakeCore(),
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
