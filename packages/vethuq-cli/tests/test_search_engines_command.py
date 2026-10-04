import json

from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app
from vethuq_core.paths import Paths
from vethuq_core.search.engines.catalog import SearchEngineCatalog
from vethuq_core.storage import open_storage

runner = CliRunner()


class TestSearchEnginesList:
    def test_lists_engines_with_like_as_default(self, use_temp_db):
        use_temp_db()
        result = runner.invoke(app, ["search-engines", "list"])
        assert result.exit_code == 0
        assert "like" in result.output
        assert "search-like" in result.output
        assert "default" in result.output

    def test_all_shows_installed_but_not_enabled_engines(self, use_temp_db, monkeypatch):
        use_temp_db()
        monkeypatch.setattr(console, "width", 200)
        root = Paths.default_data_root()
        (root / SearchEngineCatalog.SELECTION_FILENAME).write_text(
            json.dumps({"enabled": []}), encoding="utf-8"
        )
        result = runner.invoke(app, ["search-engines", "list", "--all"])
        assert result.exit_code == 0
        assert "not enabled" in result.output


class TestVersion:
    def test_shows_and_stores_search_engines(self, use_temp_db):
        db_path = use_temp_db()
        result = runner.invoke(app, ["--version"])
        assert "search-like" in result.output
        storage = open_storage(db_path)
        try:
            stored = json.loads(storage.get_setting_value("installed_search_engines"))
        finally:
            storage.close()
        assert "search-like" in stored
