import json
import sys
import types
from pathlib import Path

import pytest
from vethuq_core.index.runner import IndexRunner
from vethuq_core.ocr.models import OcrModels
from vethuq_core.ocr.models.fetch import ModelFetch

DET = "PP-OCRv5_server_det"
DOC_ORI = "PP-LCNet_x1_0_doc_ori"
LINE_ORI = "PP-LCNet_x1_0_textline_ori"
EN_REC = "en_PP-OCRv5_mobile_rec"
TE_REC = "te_PP-OCRv5_mobile_rec"
SHARED = [DET, DOC_ORI, LINE_ORI]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path / "paddlex"))
    return tmp_path / "paddlex" / "official_models"


def _model(cache: Path, name: str, size: int = 10) -> Path:
    folder = cache / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "inference.pdiparams").write_bytes(b"x" * size)
    return folder


class TestLayout:
    def test_cache_follows_the_paddlex_environment_variable(self, cache):
        assert OcrModels.cache_dir() == cache

    def test_cache_defaults_to_the_paddlex_folder_in_the_home_directory(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("PADDLE_PDX_CACHE_HOME", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        assert OcrModels.cache_dir() == tmp_path / ".paddlex" / "official_models"

    def test_shared_models_come_from_the_engine_manifest(self):
        assert list(OcrModels.shared()) == SHARED

    def test_a_language_owns_its_recognizer(self):
        assert OcrModels.own("en") == (EN_REC,)
        assert OcrModels.own("te") == (TE_REC,)

    def test_an_unknown_language_owns_nothing(self):
        assert OcrModels.own("xx") == ()
        assert OcrModels.required("xx") == SHARED

    def test_required_is_shared_then_own(self):
        assert OcrModels.required("te") == [*SHARED, TE_REC]

    def test_every_model_is_listed_with_the_languages_that_need_it(self):
        known = OcrModels.managed()

        assert known[DET] == ("en", "te")
        assert known[EN_REC] == ("en",)
        assert known[TE_REC] == ("te",)


class TestStatus:
    def test_nothing_is_downloaded_in_an_empty_cache(self, cache):
        statuses = OcrModels.status(["te"])

        assert [s.name for s in statuses] == [*SHARED, TE_REC]
        assert not any(s.present for s in statuses)
        assert all(s.size_bytes == 0 for s in statuses)

    def test_present_models_report_their_size(self, cache):
        _model(cache, DET, size=100)
        _model(cache, TE_REC, size=40)

        by_name = {s.name: s for s in OcrModels.status(["te"])}

        assert by_name[DET].present and by_name[DET].size_bytes == 100
        assert by_name[TE_REC].present and by_name[TE_REC].size_bytes == 40
        assert not by_name[DOC_ORI].present

    def test_shared_models_are_flagged_and_listed_first(self, cache):
        statuses = OcrModels.status()

        assert [s.shared for s in statuses[:3]] == [True, True, True]
        assert [s.name for s in statuses] == [*SHARED, EN_REC, TE_REC]
        assert statuses[3].languages == ("en",)

    def test_an_empty_folder_is_not_a_model(self, cache):
        (cache / DET).mkdir(parents=True)

        assert not OcrModels.is_present(DET)

    def test_missing_and_ready(self, cache):
        for name in SHARED:
            _model(cache, name)

        assert OcrModels.missing("te") == [TE_REC]
        assert not OcrModels.is_ready("te")
        _model(cache, TE_REC)
        assert OcrModels.is_ready("te")
        assert not OcrModels.is_ready("en")


class TestClear:
    def test_removes_a_languages_own_models_and_keeps_the_shared_ones(self, cache):
        for name in (*SHARED, EN_REC, TE_REC):
            _model(cache, name)

        result = OcrModels.clear(["te"])

        assert result.removed == [TE_REC]
        assert result.kept_shared == SHARED
        assert not (cache / TE_REC).exists()
        assert (cache / EN_REC).exists()
        assert all((cache / name).exists() for name in SHARED)

    def test_everything_removes_the_shared_models_too(self, cache):
        for name in (*SHARED, TE_REC):
            _model(cache, name)

        result = OcrModels.clear(["te"], include_shared=True)

        assert set(result.removed) == {TE_REC, *SHARED}
        assert result.kept_shared == []
        assert not any((cache / name).exists() for name in (*SHARED, TE_REC))

    def test_a_model_that_is_not_there_is_reported_not_an_error(self, cache):
        result = OcrModels.clear(["te"])

        assert result.removed == []
        assert result.absent == [TE_REC]

    def test_unrelated_folders_are_never_touched(self, cache):
        _model(cache, "SomeoneElses_model")
        _model(cache, TE_REC)

        OcrModels.clear(["te"], include_shared=True)

        assert (cache / "SomeoneElses_model").exists()


class TestClean:
    def test_removes_models_of_languages_that_are_not_enabled(self, cache):
        for name in (*SHARED, EN_REC, TE_REC):
            _model(cache, name, size=5)

        result = OcrModels.clean(["en"])

        assert result.removed == [TE_REC]
        assert result.bytes_freed == 5
        assert (cache / EN_REC).exists()
        assert all((cache / name).exists() for name in SHARED)

    def test_keeps_everything_that_is_in_use(self, cache):
        for name in (*SHARED, EN_REC, TE_REC):
            _model(cache, name)

        assert OcrModels.clean(["en", "te"]).removed == []

    def test_removes_an_empty_leftover_folder_of_a_model_in_use(self, cache):
        (cache / EN_REC).mkdir(parents=True)

        assert OcrModels.clean(["en"]).removed == [EN_REC]
        assert not (cache / EN_REC).exists()

    def test_leaves_other_programs_models_alone_and_lists_them(self, cache):
        _model(cache, "SomeoneElses_model")

        result = OcrModels.clean(["en"])

        assert result.removed == []
        assert result.unmanaged == ["SomeoneElses_model"]
        assert (cache / "SomeoneElses_model").exists()

    def test_a_missing_cache_has_nothing_to_clean(self, cache):
        result = OcrModels.clean(["en"])

        assert result.removed == [] and result.unmanaged == []


class TestDownload:
    @staticmethod
    def _fake_fetch(monkeypatch, outcomes: dict[str, str], exit_code: int = 0):
        """Replace the child process: report each requested model with the given outcome."""
        requested: list[list[str]] = []

        def run(names, on_event):
            requested.append(list(names))
            for name in names:
                on_event({"model": name, "status": "downloading"})
                outcome = outcomes.get(name, "ready")
                if outcome == "ready":
                    on_event({"model": name, "status": "ready"})
                elif outcome == "failed":
                    on_event({"model": name, "status": "failed", "error": "no network"})
            return exit_code

        monkeypatch.setattr(OcrModels, "_run_fetch", staticmethod(run))
        return requested

    def test_downloads_what_is_missing(self, cache, monkeypatch):
        _model(cache, DET)
        requested = self._fake_fetch(monkeypatch, {})

        result = OcrModels.download(["te"])

        assert requested == [[DOC_ORI, LINE_ORI, TE_REC]]
        assert result.downloaded == [DOC_ORI, LINE_ORI, TE_REC]
        assert result.already_present == [DET]
        assert result.ok

    def test_does_nothing_when_everything_is_there(self, cache, monkeypatch):
        for name in (*SHARED, TE_REC):
            _model(cache, name)
        requested = self._fake_fetch(monkeypatch, {})

        result = OcrModels.download(["te"])

        assert requested == []
        assert result.downloaded == [] and result.ok
        assert result.already_present == [*SHARED, TE_REC]

    def test_several_languages_share_the_common_models(self, cache, monkeypatch):
        requested = self._fake_fetch(monkeypatch, {})

        OcrModels.download(["en", "te"])

        assert requested == [[*SHARED, EN_REC, TE_REC]]

    def test_reports_progress_per_model(self, cache, monkeypatch):
        self._fake_fetch(monkeypatch, {TE_REC: "failed"})
        seen = []

        OcrModels.download(["te"], on_progress=lambda name, state: seen.append((name, state)))

        assert (TE_REC, "downloading") in seen
        assert (TE_REC, "failed") in seen
        assert (DET, "ready") in seen

    def test_a_failed_model_is_reported_with_its_reason(self, cache, monkeypatch):
        self._fake_fetch(monkeypatch, {TE_REC: "failed"}, exit_code=1)

        result = OcrModels.download(["te"])

        assert not result.ok
        assert result.failed == {TE_REC: "no network"}
        assert TE_REC not in result.downloaded
        assert DET in result.downloaded

    def test_a_model_the_child_never_mentioned_is_a_failure(self, cache, monkeypatch):
        self._fake_fetch(monkeypatch, {TE_REC: "silent"}, exit_code=3)

        result = OcrModels.download(["te"])

        assert "exit code 3" in result.failed[TE_REC]

    def test_force_removes_and_fetches_again(self, cache, monkeypatch):
        for name in (*SHARED, TE_REC):
            _model(cache, name)
        requested = self._fake_fetch(monkeypatch, {})

        result = OcrModels.download(["te"], force=True)

        assert requested == [[*SHARED, TE_REC]]
        assert result.already_present == []
        assert not (cache / TE_REC).exists()  # the fake child downloads nothing

    def test_a_child_that_cannot_start_fails_every_model(self, cache, monkeypatch):
        def broken(names, on_event):
            raise OSError("no such executable")

        monkeypatch.setattr(OcrModels, "_run_fetch", staticmethod(broken))

        result = OcrModels.download(["te"])

        assert set(result.failed) == {*SHARED, TE_REC}
        assert "no such executable" in result.failed[TE_REC]

    def test_events_for_other_models_are_ignored(self, cache, monkeypatch):
        def run(names, on_event):
            on_event({"model": "Stranger", "status": "ready"})
            for name in names:
                on_event({"model": name, "status": "ready"})
            return 0

        monkeypatch.setattr(OcrModels, "_run_fetch", staticmethod(run))

        assert "Stranger" not in OcrModels.download(["te"]).downloaded


class TestChildProcess:
    def test_command_runs_the_fetch_module_with_this_interpreter(self):
        command = OcrModels._fetch_command([TE_REC])

        assert command == [sys.executable, "-m", "vethuq_core.ocr.models.fetch", TE_REC]

    def test_frozen_build_runs_the_worker_executable(self, tmp_path, monkeypatch):
        worker = tmp_path / "vethuq-worker.exe"
        worker.write_text("")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "vethuq.exe"))

        assert OcrModels._fetch_command([TE_REC]) == [str(worker), "--fetch-models", TE_REC]

    def test_frozen_build_without_the_worker_says_so(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "vethuq.exe"))

        with pytest.raises(FileNotFoundError):
            OcrModels._fetch_command([TE_REC])

    def test_status_lines_are_read_and_noise_is_skipped(self, monkeypatch):
        script = (
            "import json;"
            "print('Downloading...');"
            "print(json.dumps({'model': 'a', 'status': 'ready'}));"
            "print(json.dumps([1, 2]));"
            "print(json.dumps({'model': 'b', 'status': 'failed', 'error': 'x'}))"
        )
        monkeypatch.setattr(
            OcrModels, "_fetch_command", staticmethod(lambda names: [sys.executable, "-c", script])
        )
        events = []

        code = OcrModels._run_fetch(["a", "b"], events.append)

        assert code == 0
        assert events == [
            {"model": "a", "status": "ready"},
            {"model": "b", "status": "failed", "error": "x"},
        ]


class TestModelFetch:
    @staticmethod
    def _install_fake_paddlex(monkeypatch, failing=()):
        class Models:
            fetched: list[str] = []

            def __getitem__(self, name):
                if name in failing:
                    raise RuntimeError(f"cannot fetch {name}")
                Models.fetched.append(name)
                return Path(name)

        module = types.ModuleType("paddlex.inference.utils.official_models")
        module.official_models = Models()
        monkeypatch.setitem(sys.modules, "paddlex.inference.utils.official_models", module)
        return Models

    @staticmethod
    def _events(capsys):
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    def test_fetches_each_model_and_reports_it(self, monkeypatch, capsys):
        models = self._install_fake_paddlex(monkeypatch)

        code = ModelFetch.main(["m1", "m2"])

        assert code == 0
        assert models.fetched == ["m1", "m2"]
        assert self._events(capsys) == [
            {"model": "m1", "status": "downloading"},
            {"model": "m1", "status": "ready"},
            {"model": "m2", "status": "downloading"},
            {"model": "m2", "status": "ready"},
        ]

    def test_a_failure_is_reported_and_the_rest_still_download(self, monkeypatch, capsys):
        models = self._install_fake_paddlex(monkeypatch, failing={"m1"})

        code = ModelFetch.main(["m1", "m2"])

        assert code == 1
        assert models.fetched == ["m2"]
        events = self._events(capsys)
        assert {"model": "m1", "status": "failed", "error": "cannot fetch m1"} in events
        assert {"model": "m2", "status": "ready"} in events

    def test_without_paddlex_every_model_fails_cleanly(self, monkeypatch, capsys):
        monkeypatch.setitem(sys.modules, "paddlex.inference.utils.official_models", None)

        code = ModelFetch.main(["m1"])

        assert code == 1
        [event] = self._events(capsys)
        assert event["status"] == "failed"
        assert "not installed" in event["error"]


class TestWorkerEntryPoint:
    def test_the_worker_runs_the_download_for_its_flag(self, monkeypatch):
        seen = []
        monkeypatch.setattr(sys, "argv", ["vethuq-worker", "--fetch-models", "m1", "m2"])
        monkeypatch.setattr(ModelFetch, "main", staticmethod(lambda names: seen.append(names) or 7))

        with pytest.raises(SystemExit) as stop:
            IndexRunner.main()

        assert seen == [["m1", "m2"]]
        assert stop.value.code == 7
