import pytest
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import open_storage

runner = CliRunner()
BASE = ["settings", "search", "semantic"]


def _read(getter):
    storage = open_storage()
    try:
        return getter(storage)
    finally:
        storage.close()


class TestSemanticThreshold:
    def test_show_defaults_to_balanced(self, use_temp_db):
        use_temp_db()
        result = runner.invoke(app, [*BASE, "threshold", "show"])
        assert result.exit_code == 0
        assert "balanced" in result.stdout and "80%" in result.stdout

    @pytest.mark.parametrize(
        ("value", "shown"), [("strict", "86%"), ("loose", "75%"), ("0.9", "90%"), ("78%", "78%")]
    )
    def test_set_then_show(self, use_temp_db, value, shown):
        use_temp_db()
        assert runner.invoke(app, [*BASE, "threshold", "set", value]).exit_code == 0
        result = runner.invoke(app, [*BASE, "threshold", "show"])
        assert value in result.stdout and shown in result.stdout

    @pytest.mark.parametrize("value", ["tight", "0", "150", "x"])
    def test_set_rejects_invalid_values(self, use_temp_db, value):
        use_temp_db()
        result = runner.invoke(app, [*BASE, "threshold", "set", value])
        assert result.exit_code == 1
        assert _read(SearchSettings.get_semantic_threshold_setting) == "balanced"

    def test_it_does_not_change_the_fuzzy_threshold(self, use_temp_db):
        use_temp_db()
        runner.invoke(app, [*BASE, "threshold", "set", "strict"])
        assert _read(SearchSettings.get_fuzzy_threshold_setting) == "balanced"


class TestSemanticLimit:
    def test_show_defaults_to_25(self, use_temp_db):
        use_temp_db()
        result = runner.invoke(app, [*BASE, "limit", "show"])
        assert result.exit_code == 0 and "25 pages" in result.stdout

    def test_set_then_show(self, use_temp_db):
        use_temp_db()
        assert runner.invoke(app, [*BASE, "limit", "set", "40"]).exit_code == 0
        assert "40 pages" in runner.invoke(app, [*BASE, "limit", "show"]).stdout

    @pytest.mark.parametrize("value", ["0", "1001", "many", "2.5"])
    def test_set_rejects_invalid_values(self, use_temp_db, value):
        use_temp_db()
        assert runner.invoke(app, [*BASE, "limit", "set", value]).exit_code == 1
        assert _read(SearchSettings.get_semantic_limit) == 25


class TestSemanticCombine:
    def test_show_defaults_to_off(self, use_temp_db):
        use_temp_db()
        result = runner.invoke(app, [*BASE, "combine", "show"])
        assert result.exit_code == 0 and "off" in result.stdout

    @pytest.mark.parametrize("value", ["full-text", "lexical", "off"])
    def test_set_then_show(self, use_temp_db, value):
        use_temp_db()
        assert runner.invoke(app, [*BASE, "combine", "set", value]).exit_code == 0
        assert value in runner.invoke(app, [*BASE, "combine", "show"]).stdout
        assert _read(SearchSettings.get_semantic_combine) == value

    @pytest.mark.parametrize("value", ["fuzzy", "like", "on"])
    def test_set_rejects_other_engines(self, use_temp_db, value):
        use_temp_db()
        assert runner.invoke(app, [*BASE, "combine", "set", value]).exit_code == 1
        assert _read(SearchSettings.get_semantic_combine) == "off"


class TestEngineSetting:
    def test_semantic_can_be_the_default_engine(self, use_temp_db):
        use_temp_db()
        assert (
            runner.invoke(app, ["settings", "search", "engine", "set", "semantic"]).exit_code == 0
        )
        assert "semantic" in runner.invoke(app, ["settings", "search", "engine", "show"]).stdout
