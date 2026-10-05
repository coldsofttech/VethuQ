"""The background service is a desktop feature; the `vethuq` package ships without it."""

import importlib.util
from pathlib import Path

import pytest
import vethuq
from typer.testing import CliRunner
from vethuq._cli.main import app
from vethuq._core.index import Indexing, IndexRunner, Reindex


def test_the_service_code_is_not_in_the_package():
    assert importlib.util.find_spec("vethuq._core.background") is None
    assert not (Path(vethuq.__file__).parent / "_cli" / "background.py").exists()
    assert not Indexing.has_service()


def test_the_python_api_has_no_service():
    client = vethuq.Vethuq()

    assert not hasattr(client, "background_service")
    assert not any("ackground" in name for name in vethuq.__all__)


def test_the_cli_has_no_service_commands():
    result = CliRunner().invoke(app, ["background-service", "status"])

    assert result.exit_code != 0
    assert "background-service" not in CliRunner().invoke(app, ["--help"]).output
    assert "--one-off" not in CliRunner().invoke(app, ["index", "run", "--help"]).output


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr(
        IndexRunner, "start_run", staticmethod(lambda t=None, **kw: calls.append((t, kw)) or 4321)
    )
    monkeypatch.setattr(
        Reindex, "start_source", staticmethod(lambda t, **kw: calls.append((t, kw)) or 4321)
    )
    return calls


def test_index_functions_always_start_their_own_worker(started):
    client = vethuq.Vethuq()

    assert client.index.run() == 4321
    assert client.index.reindex(1) == 4321
    assert len(started) == 2
