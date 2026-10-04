import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app
from vethuq_core.errors import LanguageUnavailableError, OcrModelMissingError
from vethuq_core.index import IndexRunner, Reindex
from vethuq_core.sources import Sources
from vethuq_core.storage import open_storage

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide(monkeypatch):
    monkeypatch.setattr(console, "width", 200)


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "docs"
    path.mkdir()
    return path


def _source_languages(path):
    storage = open_storage()
    try:
        return Sources.get(storage, str(path)).languages
    finally:
        storage.close()


class TestIndexRunLang:
    @pytest.mark.parametrize(
        "args, expected",
        [
            ([], None),
            (["--lang", "te"], "te"),
            (["--lang", "en,te"], "en,te"),
            (["--lang", "en", "--lang", "te"], "en,te"),
            (["--lang", "auto"], "auto"),
        ],
    )
    def test_run_hands_the_languages_to_the_runner(self, use_temp_db, folder, args, expected):
        use_temp_db()
        runner.invoke(app, ["source", "add", str(folder)])

        with patch.object(IndexRunner, "start_run", return_value=4321) as start:
            result = runner.invoke(app, ["index", "run", *args])

        assert result.exit_code == 0
        assert start.call_args.kwargs["languages"] == expected

    def test_restart_takes_the_option_too(self, use_temp_db, folder):
        use_temp_db()
        runner.invoke(app, ["source", "add", str(folder)])

        with patch.object(IndexRunner, "start_run", return_value=4321) as start:
            result = runner.invoke(app, ["index", "restart", "--lang", "te"])

        assert result.exit_code == 0
        assert start.call_args.kwargs["languages"] == "te"
        assert start.call_args.kwargs["restart"] is True

    def test_reindex_a_source(self, use_temp_db):
        use_temp_db()

        with patch.object(Reindex, "start_source", return_value=4321) as start:
            result = runner.invoke(app, ["index", "reindex", "1", "--force", "--lang", "te"])

        assert result.exit_code == 0
        assert start.call_args.kwargs["languages"] == "te"

    def test_reindex_a_file(self, use_temp_db):
        use_temp_db()

        with patch.object(Reindex, "start_file", return_value=4321) as start:
            result = runner.invoke(app, ["index", "reindex", "file", "x.png", "--lang", "te"])

        assert result.exit_code == 0
        assert start.call_args.kwargs["languages"] == "te"

    def test_reindex_without_the_option_passes_none(self, use_temp_db):
        use_temp_db()

        with patch.object(Reindex, "start_file", return_value=4321) as start:
            runner.invoke(app, ["index", "reindex", "file", "x.png"])

        assert start.call_args.kwargs["languages"] is None

    @pytest.mark.parametrize(
        "error",
        [
            LanguageUnavailableError("The Telugu OCR language is not installed.", "Install it."),
            OcrModelMissingError("The Telugu OCR models are not downloaded.", "Download them."),
        ],
    )
    def test_a_language_problem_is_a_startup_error_with_its_hint(self, use_temp_db, folder, error):
        use_temp_db()
        runner.invoke(app, ["source", "add", str(folder)])

        with patch.object(IndexRunner, "start_run", side_effect=error):
            result = runner.invoke(app, ["index", "run", "--lang", "te"])

        assert result.exception is error
        assert error.hint


class TestSourceAddLang:
    def test_a_source_can_be_added_with_languages(self, use_temp_db, folder):
        use_temp_db()

        result = runner.invoke(app, ["source", "add", str(folder), "--lang", "te"])

        assert result.exit_code == 0
        assert "Languages: te" in result.output
        assert _source_languages(folder) == "te"

    def test_several_languages(self, use_temp_db, folder):
        use_temp_db()

        runner.invoke(app, ["source", "add", str(folder), "--lang", "te,en"])

        assert _source_languages(folder) == "en,te"

    def test_without_the_option_nothing_is_recorded_or_shown(self, use_temp_db, folder):
        use_temp_db()

        result = runner.invoke(app, ["source", "add", str(folder)])

        assert "Languages:" not in result.output
        assert _source_languages(folder) is None

    def test_an_unknown_language_is_refused_and_nothing_is_added(self, use_temp_db, folder):
        use_temp_db()

        result = runner.invoke(app, ["source", "add", str(folder), "--lang", "xx"])

        assert result.exit_code == 1
        assert "Unknown language 'xx'" in result.output
        storage = open_storage()
        try:
            assert Sources.list_all(storage) == []
        finally:
            storage.close()


class TestSetLanguages:
    @pytest.fixture
    def registered(self, use_temp_db, folder):
        use_temp_db()
        runner.invoke(app, ["source", "add", str(folder)])
        return folder

    def test_sets_the_languages(self, registered):
        result = runner.invoke(app, ["source", "set-languages", str(registered), "te"])

        assert result.exit_code == 0
        assert "te" in result.output
        assert _source_languages(registered) == "te"

    def test_by_id_and_several(self, registered):
        result = runner.invoke(app, ["source", "set-languages", "1", "te", "en"])

        assert result.exit_code == 0
        assert _source_languages(registered) == "en,te"

    def test_reset_goes_back_to_the_setting(self, registered):
        runner.invoke(app, ["source", "set-languages", "1", "te"])

        result = runner.invoke(app, ["source", "set-languages", "1", "--reset"])

        assert result.exit_code == 0
        assert "the ocr_languages setting" in result.output
        assert _source_languages(registered) is None

    @pytest.mark.parametrize("args", [["1"], ["1", "te", "--reset"]])
    def test_languages_or_reset_but_not_neither_or_both(self, registered, args):
        result = runner.invoke(app, ["source", "set-languages", *args])

        assert result.exit_code == 1
        assert "or --reset" in result.output

    def test_unknown_language_and_unknown_source(self, registered):
        bad_language = runner.invoke(app, ["source", "set-languages", "1", "xx"])
        bad_source = runner.invoke(app, ["source", "set-languages", "99", "te"])

        assert bad_language.exit_code == 1 and "Unknown language" in bad_language.output
        assert bad_source.exit_code == 1 and "No active source" in bad_source.output


class TestSettingsOcrLanguages:
    def test_shows_the_default_and_what_is_installed(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "ocr", "languages", "show"])

        assert result.exit_code == 0
        assert "OCR languages: auto" in result.output
        assert "Installed and enabled: en, te" in result.output

    def test_set_show_reset(self, use_temp_db):
        use_temp_db()

        set_result = runner.invoke(app, ["settings", "ocr", "languages", "set", "te", "en"])
        show = runner.invoke(app, ["settings", "ocr", "languages", "show"])
        reset = runner.invoke(app, ["settings", "ocr", "languages", "reset"])
        after = runner.invoke(app, ["settings", "ocr", "languages", "show"])

        assert set_result.exit_code == 0 and "en,te" in set_result.output
        assert "OCR languages: en,te" in show.output
        assert reset.exit_code == 0 and "auto" in reset.output
        assert "OCR languages: auto" in after.output

    def test_a_comma_separated_value(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "ocr", "languages", "set", "en,te"])

        assert result.exit_code == 0 and "en,te" in result.output

    def test_an_unknown_language_is_refused(self, use_temp_db):
        use_temp_db()

        result = runner.invoke(app, ["settings", "ocr", "languages", "set", "xx"])

        assert result.exit_code == 1
        assert "Unknown language 'xx'" in result.output
        shown = runner.invoke(app, ["settings", "ocr", "languages", "show"])
        assert "OCR languages: auto" in shown.output

    def test_the_languages_file_limits_what_is_shown_as_enabled(self, use_temp_db):
        from vethuq_core.paths import Paths

        use_temp_db()
        (Paths.default_data_root() / "languages.json").write_text(
            json.dumps({"enabled": ["en"]}), encoding="utf-8"
        )

        result = runner.invoke(app, ["settings", "ocr", "languages", "show"])

        assert "Installed and enabled: en" in result.output
        assert "en, te" not in result.output
