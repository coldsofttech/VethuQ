from __future__ import annotations

import pytest

from vethuq._paths import _Paths


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path_factory, monkeypatch):
    """Keep tests from reading or creating folders in the real per-user data/config dirs."""
    root = tmp_path_factory.mktemp("data_root")
    monkeypatch.delenv(_Paths.ENV_VAR, raising=False)
    monkeypatch.setattr(_Paths, "platform_data_root", staticmethod(lambda: root))
    monkeypatch.setattr(
        _Paths, "location_file", staticmethod(lambda: root / "config" / "db.json")
    )
