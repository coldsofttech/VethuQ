from __future__ import annotations

import json
from pathlib import Path

import pytest

import vethuq
from tests import fake_pipeline as fp
from tests.language_addons import TELUGU, LanguageAddonFactory
from vethuq import errors
from vethuq.file_types import FileType, FileTypes
from vethuq.ocr import Ocr, OcrEngine, OcrModel, OcrPhase


@pytest.fixture
def telugu(tmp_path_factory, monkeypatch):
    import sys

    folder = tmp_path_factory.mktemp("telugu")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    LanguageAddonFactory.install(folder, "telugu", [TELUGU])


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


class TestFileTypes:
    def test_pdf_is_listed(self, client):
        assert isinstance(client.file_types, FileTypes)
        (pdf,) = client.file_types.list()
        assert pdf == FileType("pdf", "PDF", (".pdf",), True, "")

    def test_get(self, client):
        assert client.file_types.get(" PDF ").id == "pdf"
        assert client.file_types.get("docx") is None

    def test_an_unavailable_type_says_why(self, client):
        fp.STATE.pdf_available = False
        (pdf,) = client.file_types.list()
        assert (pdf.available, pdf.reason) == (False, "the PDF reader is off")

    def test_dict_and_json(self, client):
        pdf = client.file_types.get("pdf")
        assert pdf.to_dict() == {
            "id": "pdf",
            "label": "PDF",
            "extensions": [".pdf"],
            "available": True,
            "reason": "",
        }
        assert json.loads(pdf.to_json()) == pdf.to_dict()


class TestEnginesAndPhases:
    def test_engines(self, client):
        assert isinstance(client.ocr, Ocr)
        (engine,) = client.ocr.engines.list()
        assert engine == OcrEngine("paddle", "Fake OCR", ("mobile",), True, "")
        fp.STATE.engine_available = False
        assert client.ocr.engines.list()[0].reason == "the fake engine is off"
        assert json.loads(engine.to_json()) == engine.to_dict()

    def test_phases(self, client):
        (phase,) = client.ocr.phases.list()
        assert phase == OcrPhase("quick", "Quick", 1, (0,), "mobile", True, "")
        assert phase.to_dict()["angles"] == [0]
        fp.STATE.phase_available = False
        assert client.ocr.phases.list()[0].reason == "the phase is off"
        assert json.loads(phase.to_json()) == phase.to_dict()


class TestModels:
    def test_listing_says_what_is_installed(self, client):
        models = client.ocr.models.list()
        assert [(m.name, m.shared, m.installed, m.languages) for m in models] == [
            ("det-mobile", True, False, ("en",)),
            ("rec-en", False, False, ("en",)),
        ]
        assert all(isinstance(m, OcrModel) and m.engine == "paddle" for m in models)

    def test_the_cache_dir_is_under_the_data_root(self, client):
        assert client.ocr.models.cache_dir.name == "models"

    def test_download_fetches_what_is_missing(self, client):
        seen = []
        models = client.ocr.models.download(on_progress=lambda name, state: seen.append(state))
        assert all(m.installed and m.size_bytes == 10 for m in models)
        assert seen == ["ready", "ready"]
        client.ocr.models.download()
        assert fp.STATE.downloads == ["det-mobile", "rec-en"]  # nothing fetched twice

    def test_a_failed_download_is_an_error(self, client):
        fp.STATE.download_fails = {"rec-en"}
        with pytest.raises(errors.OcrModelMissingError, match="rec-en: no network"):
            client.ocr.models.download()
        assert [m.installed for m in client.ocr.models.list()] == [True, False]

    def test_redownload_replaces_models(self, client):
        client.ocr.models.download()
        fp.STATE.downloads.clear()
        client.ocr.models.redownload(["rec-en"])
        assert fp.STATE.downloads == ["rec-en"]
        client.ocr.models.redownload()
        assert fp.STATE.downloads[1:] == ["det-mobile", "rec-en"]

    def test_listing_by_language(self, telugu, client):
        assert [m.name for m in client.ocr.models.list(["te"])] == ["det-mobile", "rec-te"]
        with pytest.raises(errors.InvalidSettingValueError):
            client.ocr.models.list(["xx"])
        with pytest.raises(TypeError):
            client.ocr.models.list("en")

    def test_clear_keeps_shared_models_by_default(self, telugu, client):
        client.ocr.models.download()
        assert client.ocr.models.clear(["te"]) == ["rec-te"]
        assert {m.name: m.installed for m in client.ocr.models.list()} == {
            "det-mobile": True,
            "rec-en": True,
            "rec-te": False,
        }

    def test_clear_with_shared(self, client):
        client.ocr.models.download()
        assert client.ocr.models.clear(["en"], include_shared=True) == ["det-mobile", "rec-en"]
        assert not any(m.installed for m in client.ocr.models.list())

    def test_clean_removes_models_nobody_needs(self, client):
        client.ocr.models.download()
        stray = client.ocr.models.cache_dir / "fake" / "rec-xx"
        stray.mkdir(parents=True)
        (stray / "model.bin").write_bytes(b"x")
        assert client.ocr.models.clean() == ["rec-xx"]
        assert not stray.exists()
        assert client.ocr.models.clean() == []

    def test_clean_with_nothing_downloaded(self, client):
        assert client.ocr.models.clean() == []

    def test_dict_and_json(self, client):
        model = client.ocr.models.list()[0]
        assert model.to_dict()["languages"] == ["en"]
        assert json.loads(model.to_json()) == model.to_dict()
        assert Path(model.path).name == "det-mobile"

    def test_clearing_makes_the_next_read_fetch_again(self, client, tmp_path):
        folder = tmp_path / "d"
        folder.mkdir()
        (folder / "s.pdf").write_text(fp.pdf_document(fp.scanned_page()))
        client.settings.index.set_stability_check_seconds(0)
        client.sources.create(folder)
        client.index.run()
        assert fp.STATE.downloads == ["det-mobile", "rec-en"]
        client.ocr.models.clear(["en"], include_shared=True)
        (folder / "t.pdf").write_text(fp.pdf_document(fp.scanned_page("another scan")))
        client.index.run()
        assert fp.STATE.downloads == ["det-mobile", "rec-en"] * 2


class TestIndexSettings:
    def test_defaults_and_changes(self, client):
        s = client.settings.index
        assert (s.get_workers(), s.get_retry_attempts(), s.get_stability_check_seconds()) == (
            "auto",
            3,
            1.0,
        )
        s.set_workers(4)
        s.set_retry_attempts(0)
        s.set_stability_check_seconds(0.5)
        assert (s.get_workers(), s.get_retry_attempts(), s.get_stability_check_seconds()) == (
            4,
            0,
            0.5,
        )
        s.reset_workers()
        s.reset_retry_attempts()
        s.reset_stability_check_seconds()
        assert (s.get_workers(), s.get_retry_attempts(), s.get_stability_check_seconds()) == (
            "auto",
            3,
            1.0,
        )

    @pytest.mark.parametrize("value", [-1, 9, "many", 1.5, True, None])
    def test_bad_workers(self, client, value):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.index.set_workers(value)

    def test_workers_accepts_auto_and_zero(self, client):
        client.settings.index.set_workers("AUTO")
        assert client.settings.index.get_workers() == "auto"
        client.settings.index.set_workers(0)
        assert client.settings.index.get_workers() == 0

    @pytest.mark.parametrize("value", [-1, 1.5, True, "3"])
    def test_bad_retry_attempts(self, client, value):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.index.set_retry_attempts(value)

    @pytest.mark.parametrize("value", [-1, True, "1", None])
    def test_bad_stability_check(self, client, value):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.index.set_stability_check_seconds(value)

    def test_damaged_saved_values_fall_back(self, client):
        from vethuq._settings import _IndexSettings, _Settings

        with client._db().session() as session:
            _Settings.set(session, _IndexSettings.WORKERS_KEY, "lots")
            _Settings.set(session, _IndexSettings.RETRY_ATTEMPTS_KEY, "x")
            _Settings.set(session, _IndexSettings.STABILITY_CHECK_KEY, "-4")
        s = client.settings.index
        assert (s.get_workers(), s.get_retry_attempts(), s.get_stability_check_seconds()) == (
            "auto",
            3,
            1.0,
        )
