"""Settings every test in the workspace shares."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _never_the_real_device_folder(tmp_path_factory, monkeypatch):
    """VethuQ keeps licences and the credit ledger in a folder shared by every account on the
    computer (`/var/lib/vethuq`, `%PROGRAMDATA%\\VethuQ`). A test must never read or create the real
    one, so it gets a folder of its own."""
    try:
        from vethuq._paths import _Paths
    except ImportError:  # a package whose tests do not need VethuQ's core
        return
    folder = tmp_path_factory.mktemp("device_root")
    monkeypatch.setattr(_Paths, "platform_device_root", staticmethod(lambda: folder))
    monkeypatch.delenv("VETHUQ_DEVICE_HOME", raising=False)
