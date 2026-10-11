from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner
from vethuq_cli.main import build_app
from vethuq_cli.state import State


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VETHUQ_HOME", str(tmp_path / "home"))
    State.reset()
    State.db_path = tmp_path / "db" / "vethuq.db"
    yield
    State.reset()


@pytest.fixture
def run():
    """`run("source", "list")` runs the CLI and returns the result."""

    def invoke(*args: str):
        State.json = False
        return CliRunner().invoke(build_app(), list(args))

    return invoke


@pytest.fixture
def run_json(run):
    def invoke(*args: str):
        result = run("--json", *args)
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    return invoke


@pytest.fixture
def docs(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text("hello museum world")
    (folder / "b.txt").write_text("another page about cats")
    return folder
