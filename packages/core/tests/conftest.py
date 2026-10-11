from __future__ import annotations

import sys

import pytest

from tests import fake_pipeline
from tests.language_addons import ENGLISH, LanguageAddonFactory
from vethuq._paths import _Paths


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path_factory, monkeypatch):
    """Keep tests from reading or creating folders in the real per-user data/config dirs."""
    root = tmp_path_factory.mktemp("data_root")
    monkeypatch.delenv(_Paths.ENV_VAR, raising=False)
    monkeypatch.setattr(_Paths, "platform_data_root", staticmethod(lambda: root))
    monkeypatch.setattr(_Paths, "location_file", staticmethod(lambda: root / "config" / "db.json"))


@pytest.fixture(autouse=True)
def _release_log_files():
    """Close the log files a test opened, so loggers don't carry one test into the next."""
    yield
    import logging

    from vethuq._logs import _Logs

    _Logs.detach_all()
    for log in _Logs.ALL.values():
        logger = log.logger()
        logger.setLevel(logging.NOTSET)
        logger.propagate = True


@pytest.fixture(autouse=True)
def _english_addon(tmp_path_factory, monkeypatch):
    """Install a stand-in for `vethuq-addon-english`, as VethuQ always has it. Tests that want
    other languages install more with `LanguageAddonFactory`."""
    folder = tmp_path_factory.mktemp("english_addon")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    module = LanguageAddonFactory.install(folder, "english", [ENGLISH])
    yield
    LanguageAddonFactory.forget(module)


@pytest.fixture(autouse=True)
def _pipeline_addons(tmp_path_factory, monkeypatch):
    """Install stand-ins for the PDF, Paddle and quick OCR add-ons, as VethuQ always has them.
    `fake_pipeline.STATE` records what they did and switches them on and off."""
    fake_pipeline.reset()
    folder = tmp_path_factory.mktemp("pipeline_addons")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    fake_pipeline.install(folder)
    yield
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
        if name.rsplit(".", 1)[-1] in {"pdf", "paddle", "ocr_quick", "ocr-quick"}:
            del sys.modules[name]
