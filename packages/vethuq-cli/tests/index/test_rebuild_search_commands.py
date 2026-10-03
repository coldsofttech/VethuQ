import re

import vethuq_cli.index.commands as commands_module
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.index import AlreadyRunningError, SearchIndexRebuildResult

runner = CliRunner()


def _flatten(output: str) -> str:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(plain.replace("│", " ").split())


def _stub_run(monkeypatch, result=None, error=None):
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(commands_module.SearchIndexRebuild, "run", staticmethod(fake_run))
    return calls


class TestRebuildSearchCommand:
    def test_declining_the_prompt_aborts_without_rebuilding(self, use_temp_db, monkeypatch):
        use_temp_db()
        calls = _stub_run(monkeypatch, SearchIndexRebuildResult())

        result = runner.invoke(app, ["index", "rebuild-search"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted." in _flatten(result.output)
        assert calls == []

    def test_confirming_rebuilds_and_shows_a_panel(self, use_temp_db, monkeypatch):
        use_temp_db()
        calls = _stub_run(
            monkeypatch,
            SearchIndexRebuildResult(rebuilt={"pdf_pages_trigram": 3, "pdf_pages_words": 3}),
        )

        result = runner.invoke(app, ["index", "rebuild-search"], input="y\n")

        out = _flatten(result.output)
        assert result.exit_code == 0
        assert len(calls) == 1
        assert "Search Index Rebuild" in out
        assert "pdf_pages_trigram rebuilt 3" in out
        assert "2 rebuilt, 0 failed" in out

    def test_force_skips_the_prompt(self, use_temp_db, monkeypatch):
        use_temp_db()
        calls = _stub_run(monkeypatch, SearchIndexRebuildResult(rebuilt={"pdf_pages_words": 1}))

        result = runner.invoke(app, ["index", "rebuild-search", "--force"])

        assert result.exit_code == 0
        assert len(calls) == 1

    def test_a_failed_table_is_reported_and_exits_non_zero(self, use_temp_db, monkeypatch):
        use_temp_db()
        _stub_run(
            monkeypatch,
            SearchIndexRebuildResult(
                rebuilt={"pdf_pages_trigram": 3}, failed={"pdf_pages_words": "malformed"}
            ),
        )

        result = runner.invoke(app, ["index", "rebuild-search", "--force"])

        out = _flatten(result.output)
        assert result.exit_code == 1
        assert "pdf_pages_words failed malformed" in out
        assert "1 rebuilt, 1 failed" in out

    def test_refused_while_an_index_run_is_active(self, use_temp_db, monkeypatch):
        use_temp_db()
        _stub_run(monkeypatch, error=AlreadyRunningError("An index run is already in progress."))

        result = runner.invoke(app, ["index", "rebuild-search", "--force"])

        assert result.exit_code == 1
        assert "already in progress" in _flatten(result.output)

    def test_runs_against_a_real_empty_database(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["index", "rebuild-search", "--force"])

        assert result.exit_code == 0
        assert "4 rebuilt, 0 failed" in _flatten(result.output)
