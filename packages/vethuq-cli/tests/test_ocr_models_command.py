import json

import pytest
from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app
from vethuq_core.ocr.models import OcrModels
from vethuq_core.paths import Paths

runner = CliRunner()

SHARED = ["PP-OCRv5_server_det", "PP-LCNet_x1_0_doc_ori", "PP-LCNet_x1_0_textline_ori"]
EN_REC = "en_PP-OCRv5_mobile_rec"
TE_REC = "te_PP-OCRv5_mobile_rec"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path / "paddlex"))
    monkeypatch.setattr(console, "width", 200)
    return tmp_path / "paddlex" / "official_models"


def _model(cache, name, size=10):
    folder = cache / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "inference.pdiparams").write_bytes(b"x" * size)


@pytest.fixture
def fake_fetch(monkeypatch):
    """The download child process replaced by one that succeeds (or fails) per model."""
    state = {"fail": set(), "requested": []}

    def run(names, on_event):
        state["requested"].append(list(names))
        for name in names:
            on_event({"model": name, "status": "downloading"})
            if name in state["fail"]:
                on_event({"model": name, "status": "failed", "error": "no network"})
            else:
                on_event({"model": name, "status": "ready"})
        return 1 if state["fail"] else 0

    monkeypatch.setattr(OcrModels, "_run_fetch", staticmethod(run))
    return state


class TestStatus:
    def test_lists_every_enabled_languages_models(self):
        result = runner.invoke(app, ["ocr", "models", "status"])

        assert result.exit_code == 0
        for name in (*SHARED, EN_REC, TE_REC):
            assert name in result.output
        assert "not downloaded" in result.output
        assert "all languages" in result.output

    def test_shows_what_is_downloaded_and_where(self, cache):
        _model(cache, TE_REC, size=2048)

        result = runner.invoke(app, ["ocr", "models", "status", "--lang", "te"])

        assert result.exit_code == 0
        assert EN_REC not in result.output
        assert "downloaded" in result.output
        assert "2.0 KB" in result.output or "2 KB" in result.output
        assert str(cache) in result.output.replace("\n", "")

    def test_accepts_comma_separated_and_all(self):
        both = runner.invoke(app, ["ocr", "models", "status", "--lang", "en,te"])
        every = runner.invoke(app, ["ocr", "models", "status", "--lang", "all"])

        assert both.exit_code == every.exit_code == 0
        assert EN_REC in both.output and TE_REC in both.output
        assert EN_REC in every.output and TE_REC in every.output

    def test_an_unknown_language_is_refused(self):
        result = runner.invoke(app, ["ocr", "models", "status", "--lang", "xx"])

        assert result.exit_code == 1
        assert "Unknown language 'xx'" in result.output

    def test_a_language_that_is_not_enabled_says_how_to_get_it(self, tmp_path):
        (Paths.default_data_root() / "languages.json").write_text(
            json.dumps({"enabled": ["en"]}), encoding="utf-8"
        )
        result = runner.invoke(app, ["ocr", "models", "status", "--lang", "te"])

        assert result.exit_code == 1
        assert "pip install vethuq[lang-te]" in result.output
        assert TE_REC not in result.output


class TestDownload:
    def test_downloads_everything_missing_for_all_enabled_languages(self, fake_fetch):
        result = runner.invoke(app, ["ocr", "models", "download"])

        assert result.exit_code == 0
        assert fake_fetch["requested"] == [[*SHARED, EN_REC, TE_REC]]
        assert "5 downloaded" in result.output

    def test_one_language_only_fetches_its_models(self, fake_fetch, cache):
        for name in SHARED:
            _model(cache, name)

        result = runner.invoke(app, ["ocr", "models", "download", "--lang", "te"])

        assert result.exit_code == 0
        assert fake_fetch["requested"] == [[TE_REC]]
        assert "1 downloaded, 3 already there" in result.output

    def test_nothing_to_do_when_all_present(self, fake_fetch, cache):
        for name in (*SHARED, TE_REC):
            _model(cache, name)

        result = runner.invoke(app, ["ocr", "models", "download", "--lang", "te"])

        assert result.exit_code == 0
        assert fake_fetch["requested"] == []
        assert "0 downloaded, 4 already there" in result.output

    def test_a_failed_download_exits_non_zero_and_says_why(self, fake_fetch):
        fake_fetch["fail"] = {TE_REC}

        result = runner.invoke(app, ["ocr", "models", "download", "--lang", "te"])

        assert result.exit_code == 1
        assert "no network" in result.output
        assert "What to do" in result.output


class TestClear:
    def test_needs_a_language(self, cache):
        _model(cache, TE_REC)

        result = runner.invoke(app, ["ocr", "models", "clear", "--force"])

        assert result.exit_code == 1
        assert "Say which language" in result.output
        assert (cache / TE_REC).exists()

    def test_removes_the_language_and_keeps_shared_models(self, cache):
        for name in (*SHARED, EN_REC, TE_REC):
            _model(cache, name)

        result = runner.invoke(app, ["ocr", "models", "clear", "--lang", "te", "--force"])

        assert result.exit_code == 0
        assert not (cache / TE_REC).exists()
        assert (cache / EN_REC).exists()
        assert all((cache / name).exists() for name in SHARED)
        assert "Kept (shared by every language)" in result.output

    def test_include_shared_removes_those_too(self, cache):
        for name in (*SHARED, TE_REC):
            _model(cache, name)

        result = runner.invoke(
            app, ["ocr", "models", "clear", "--lang", "te", "--include-shared", "--force"]
        )

        assert result.exit_code == 0
        assert not any((cache / name).exists() for name in (*SHARED, TE_REC))

    def test_asks_first_and_stops_on_no(self, cache):
        _model(cache, TE_REC)

        result = runner.invoke(app, ["ocr", "models", "clear", "--lang", "te"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        assert (cache / TE_REC).exists()

    def test_goes_ahead_on_yes(self, cache):
        _model(cache, TE_REC)

        result = runner.invoke(app, ["ocr", "models", "clear", "--lang", "te"], input="y\n")

        assert result.exit_code == 0
        assert not (cache / TE_REC).exists()


class TestReset:
    def test_deletes_and_downloads_again(self, cache, fake_fetch):
        for name in (*SHARED, TE_REC):
            _model(cache, name)

        result = runner.invoke(app, ["ocr", "models", "reset", "--lang", "te", "--force"])

        assert result.exit_code == 0
        assert fake_fetch["requested"] == [[TE_REC]]
        assert (cache / SHARED[0]).exists()  # shared models are not reset

    def test_needs_a_language(self, fake_fetch):
        result = runner.invoke(app, ["ocr", "models", "reset", "--force"])

        assert result.exit_code == 1
        assert fake_fetch["requested"] == []

    def test_a_failed_download_exits_non_zero(self, cache, fake_fetch):
        _model(cache, TE_REC)
        fake_fetch["fail"] = {TE_REC}

        result = runner.invoke(app, ["ocr", "models", "reset", "--lang", "te", "--force"])

        assert result.exit_code == 1

    def test_asks_first(self, cache, fake_fetch):
        _model(cache, TE_REC)

        result = runner.invoke(app, ["ocr", "models", "reset", "--lang", "te"], input="n\n")

        assert "Aborted" in result.output
        assert (cache / TE_REC).exists()
        assert fake_fetch["requested"] == []


class TestClean:
    def test_removes_models_of_languages_that_are_not_enabled(self, cache):
        (Paths.default_data_root() / "languages.json").write_text(
            json.dumps({"enabled": ["en"]}), encoding="utf-8"
        )
        for name in (*SHARED, EN_REC, TE_REC):
            _model(cache, name, size=1024)

        result = runner.invoke(app, ["ocr", "models", "clean", "--force"])

        assert result.exit_code == 0
        assert not (cache / TE_REC).exists()
        assert (cache / EN_REC).exists()
        assert TE_REC in result.output
        assert "freed" in result.output

    def test_leaves_other_programs_models_and_says_so(self, cache):
        _model(cache, "SomeoneElses_model")

        result = runner.invoke(app, ["ocr", "models", "clean", "--force"])

        assert result.exit_code == 0
        assert (cache / "SomeoneElses_model").exists()
        assert "SomeoneElses_model" in result.output
        assert "Removed: nothing" in result.output

    def test_asks_first(self, cache):
        (Paths.default_data_root() / "languages.json").write_text(
            json.dumps({"enabled": ["en"]}), encoding="utf-8"
        )
        _model(cache, TE_REC)

        result = runner.invoke(app, ["ocr", "models", "clean"], input="n\n")

        assert "Aborted" in result.output
        assert (cache / TE_REC).exists()
