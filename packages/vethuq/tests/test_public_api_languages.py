"""The OCR language features of the public API, as documented in docs/PYTHON_API.md."""

from pathlib import Path

import pytest
import vethuq
from vethuq._core.index import IndexRunner, Reindex
from vethuq._core.ocr.models import OcrModels


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> vethuq.Vethuq:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(
        "vethuq._core.paths.Paths.default_data_root", staticmethod(lambda: data_dir)
    )
    monkeypatch.setattr(
        "vethuq._core.paths.Paths.platform_data_root", staticmethod(lambda: data_dir)
    )
    monkeypatch.setattr(
        "vethuq._core.paths.Paths.location_file",
        staticmethod(lambda: data_dir / "config" / "location.json"),
    )
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path / "paddlex"))
    return vethuq.Vethuq()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = tmp_path / "docs"
    path.mkdir()
    return path


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch):
    """Records what the runner and reindex are asked to start."""
    calls: list[tuple[str, object]] = []

    def start_run(target=None, **kwargs):
        calls.append(("run", kwargs))
        return 4321

    def start_source(target, **kwargs):
        calls.append(("source", kwargs))
        return 4321

    def start_file(file, **kwargs):
        calls.append(("file", kwargs))
        return 4321

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(start_run))
    monkeypatch.setattr(Reindex, "start_source", staticmethod(start_source))
    monkeypatch.setattr(Reindex, "start_file", staticmethod(start_file))
    return calls


def test_the_language_names_are_public():
    for name in (
        "LanguageUnavailableError",
        "UnknownLanguageError",
        "ModelStatus",
        "DownloadResult",
        "ClearResult",
        "CleanResult",
    ):
        assert name in vethuq.__all__


# --- sources and the setting --------------------------------------------------------------


def test_a_source_can_be_added_with_languages(client: vethuq.Vethuq, folder: Path):
    assert client.sources.add(folder, languages="te, en").languages == "en,te"


def test_languages_can_be_a_list(client: vethuq.Vethuq, folder: Path):
    assert client.sources.add(folder, languages=["te", "en"]).languages == "en,te"


def test_a_source_has_no_languages_by_default(client: vethuq.Vethuq, folder: Path):
    assert client.sources.add(folder).languages is None


def test_set_languages_chooses_and_clears(client: vethuq.Vethuq, folder: Path):
    source = client.sources.add(folder)

    assert client.sources.set_languages(source.id, "te").languages == "te"
    assert client.sources.set_languages(str(folder), ["en", "te"]).languages == "en,te"
    assert client.sources.set_languages(source.id, None).languages is None


def test_an_unknown_language_is_refused(client: vethuq.Vethuq, folder: Path):
    with pytest.raises(vethuq.UnknownLanguageError):
        client.sources.add(folder, languages="xx")


def test_the_default_languages_setting(client: vethuq.Vethuq):
    languages = client.settings.ocr.languages

    assert languages.get() == "auto"
    assert languages.set(["te", "en"]) == "en,te"
    assert languages.get() == "en,te"
    languages.reset()
    assert languages.get() == "auto"


def test_an_invalid_languages_setting_is_refused(client: vethuq.Vethuq):
    with pytest.raises(vethuq.InvalidSettingValueError):
        client.settings.ocr.languages.set("xx")


# --- index --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "languages, expected",
    [(None, None), ("te", "te"), ("en,te", "en,te"), (["en", "te"], "en,te"), ("auto", "auto")],
)
def test_index_run_hands_the_languages_on(client: vethuq.Vethuq, started, languages, expected):
    client.index.run(languages=languages)
    client.index.restart(languages=languages)

    assert [kwargs["languages"] for _, kwargs in started] == [expected, expected]
    assert [kwargs["restart"] for _, kwargs in started] == [False, True]


def test_reindex_hands_the_languages_on(client: vethuq.Vethuq, started):
    client.index.reindex(1, languages=["te"])
    client.index.reindex_file("x.png", languages="te")

    assert [(kind, kwargs["languages"]) for kind, kwargs in started] == [
        ("source", "te"),
        ("file", "te"),
    ]


# --- ocr ----------------------------------------------------------------------------------


def test_ocr_languages_lists_what_can_be_used(client: vethuq.Vethuq):
    assert client.ocr.languages() == ["en", "te"]


def test_models_status_covers_every_enabled_language(client: vethuq.Vethuq):
    statuses = client.ocr.models.status()

    assert [s.name for s in statuses][-2:] == [
        "en_PP-OCRv5_mobile_rec",
        "te_PP-OCRv5_mobile_rec",
    ]
    assert not any(s.present for s in statuses)
    assert all(isinstance(s, vethuq.ModelStatus) for s in statuses)


def test_models_status_for_one_language(client: vethuq.Vethuq):
    assert "en_PP-OCRv5_mobile_rec" not in [s.name for s in client.ocr.models.status("te")]


def test_models_download_reports_what_arrived(
    client: vethuq.Vethuq, monkeypatch: pytest.MonkeyPatch
):
    def run(names, on_event):
        for name in names:
            on_event({"model": name, "status": "ready"})
        return 0

    monkeypatch.setattr(OcrModels, "_run_fetch", staticmethod(run))
    seen = []

    result = client.ocr.models.download(["te"], on_progress=lambda m, s: seen.append((m, s)))

    assert isinstance(result, vethuq.DownloadResult)
    assert result.ok and len(result.downloaded) == 4
    assert ("te_PP-OCRv5_mobile_rec", "ready") in seen


def test_models_clear_reset_and_clean(client: vethuq.Vethuq, monkeypatch: pytest.MonkeyPatch):
    cache = OcrModels.cache_dir()
    for name in ("PP-OCRv5_server_det", "te_PP-OCRv5_mobile_rec", "Someone_elses"):
        (cache / name).mkdir(parents=True)
        (cache / name / "w").write_bytes(b"x")
    monkeypatch.setattr(OcrModels, "_run_fetch", staticmethod(lambda names, on_event: 0))

    cleared = client.ocr.models.clear("te")
    reset = client.ocr.models.reset("te")
    cleaned = client.ocr.models.clean()

    assert isinstance(cleared, vethuq.ClearResult)
    assert cleared.removed == ["te_PP-OCRv5_mobile_rec"]
    assert cleared.kept_shared == ["PP-OCRv5_server_det"]
    assert isinstance(reset, vethuq.DownloadResult)
    assert isinstance(cleaned, vethuq.CleanResult)
    assert cleaned.unmanaged == ["Someone_elses"]
    assert (cache / "Someone_elses").exists()
