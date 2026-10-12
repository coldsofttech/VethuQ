"""Integration tests read with the real add-ons, so the stand-ins the unit tests install
(English, PDF, Paddle, quick OCR) are switched off here."""

from __future__ import annotations

import os

import pytest

import vethuq


@pytest.fixture(autouse=True)
def _english_addon():
    yield


@pytest.fixture(autouse=True)
def _pipeline_addons():
    yield


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        yield client


@pytest.fixture
def telugu(client):
    """Telugu is licensed: it needs the token in VETHUQ_TELUGU_LICENCE, else its tests skip."""
    token = os.environ.get("VETHUQ_TELUGU_LICENCE")
    if not token:
        pytest.skip("set VETHUQ_TELUGU_LICENCE to a Telugu licence token")
    try:
        from vethuq.addons.telugu import Telugu  # noqa: PLC0415
    except ImportError:
        pytest.skip("the Telugu add-on is not installed")
    Telugu(client).set_licence(token)
