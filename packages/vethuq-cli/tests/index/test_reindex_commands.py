import re

import pytest
import vethuq_core.db as db_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.index import Indexing
from vethuq_core.index import runner as index_runner_module
from vethuq_core.sources import Sources
from vethuq_core.storage.sqlite import SqliteStorage

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_background_service(monkeypatch):
    """These tests fake the worker's Popen; on Windows the real service lookup (`sc.exe`, run
    through subprocess.run) would use that fake too. Index as if no service is installed."""
    monkeypatch.setattr(Indexing, "service_status", staticmethod(lambda db_path=None: None))


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


def _flatten(output: str) -> str:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(plain.replace("│", " ").split())


def _add_source(db_path, folder):
    conn = db_module.Db.connect(db_path)
    try:
        return Sources.add(SqliteStorage(conn), folder).id
    finally:
        conn.close()


class TestReindexCommands:
    def test_source_argument_without_subcommand_starts_a_reindex(
        self, use_temp_db, tmp_path, monkeypatch
    ):
        db_path = use_temp_db()
        source_id = _add_source(db_path, tmp_path)
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(123)
        )

        result = runner.invoke(app, ["index", "reindex", str(source_id)], input="y\n")

        assert result.exit_code == 0
        assert "Started background reindex (pid 123)" in _flatten(result.stdout)

    def test_declining_the_confirmation_starts_nothing(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        source_id = _add_source(db_path, tmp_path)
        started = []
        monkeypatch.setattr(
            index_runner_module.subprocess,
            "Popen",
            lambda *a, **k: started.append(1) or _FakeProcess(123),
        )

        result = runner.invoke(app, ["index", "reindex", str(source_id)], input="n\n")

        assert result.exit_code == 0
        assert "Aborted." in _flatten(result.stdout)
        assert started == []

    def test_confirmation_names_the_source_and_file_count(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        source_id = _add_source(db_path, tmp_path)

        result = runner.invoke(app, ["index", "reindex", str(source_id)], input="n\n")

        text = _flatten(result.stdout)
        assert "Re-index all 0 files" in text
        assert "stays searchable" in text

    def test_force_skips_the_confirmation(self, use_temp_db, tmp_path, monkeypatch):
        db_path = use_temp_db()
        source_id = _add_source(db_path, tmp_path)
        monkeypatch.setattr(
            index_runner_module.subprocess, "Popen", lambda *a, **k: _FakeProcess(321)
        )

        result = runner.invoke(app, ["index", "reindex", str(source_id), "--force"])

        assert result.exit_code == 0
        assert "Re-index all" not in _flatten(result.stdout)
        assert "Started background reindex (pid 321)" in _flatten(result.stdout)

    def test_unknown_source_is_an_error(self, use_temp_db, monkeypatch):
        use_temp_db()

        result = runner.invoke(app, ["index", "reindex", "999"])

        assert result.exit_code == 1
        assert "Re-index all" not in _flatten(result.output)

    def test_file_not_tracked_is_an_error(self, use_temp_db, tmp_path):
        db_path = use_temp_db()
        _add_source(db_path, tmp_path)

        result = runner.invoke(app, ["index", "reindex", "file", str(tmp_path / "x.pdf")])

        assert result.exit_code == 1
        assert "isn't tracked" in _flatten(result.output)
