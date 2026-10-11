from __future__ import annotations

import pytest
from typer.testing import CliRunner
from vethuq_cli.main import build_app
from vethuq_cli.state import State

import vethuq


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.txt").write_text("hello museum world")
        client.sources.create(folder)
        yield client


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """`cli("background", "status")` runs the vethuq command line on a temporary database."""
    monkeypatch.setenv("VETHUQ_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    State.reset()
    State.db_path = tmp_path / "db2" / "vethuq.db"

    def invoke(*args):
        return CliRunner().invoke(build_app(), list(args))

    yield invoke
    State.reset()
