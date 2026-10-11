"""The worker reading pages with VethuQ's own add-ons (the stand-ins the suite installs)."""

from __future__ import annotations

import numpy

from tests import fake_pipeline
from vethuq._addons.settings import _AddonSettingsStore
from vethuq_addon_api import LanguageSpec, OcrRequest
from vethuq_worker import JobBuilder, generate_key, open_result, run_job
from vethuq_worker.worker import PAYLOAD_FILE, RESULT_FILE, CoreEngine, core_engine

KEY = generate_key()
EN = LanguageSpec("en", "English", default=True)


def job(tmp_path, *keys, language=EN, settings=None):
    builder = JobBuilder(KEY, addon_settings=settings)
    for key in keys:
        builder.add(OcrRequest(key, numpy.full((20, 30, 3), 200, dtype=numpy.uint8), language))
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / PAYLOAD_FILE).write_bytes(builder.build())
    return builder, folder


class TestCoreEngine:
    def test_pages_are_read_by_the_installed_engine(self, tmp_path):
        builder, folder = job(tmp_path, "a", "b")
        result = run_job(builder.job_id, folder, tmp_path / "out", KEY)
        assert result.status == "done"
        assert [p.engine for p in result.pages] == ["fake-ocr 1.0"] * 2
        language, image = fake_pipeline.STATE.ocr_calls[0]
        assert language == "en" and image.shape == (20, 30, 3)
        sealed = (tmp_path / "out" / RESULT_FILE).read_bytes()
        assert open_result(KEY, builder.job_id, sealed).job_id == builder.job_id

    def test_unknown_language_fails_its_page(self, tmp_path):
        builder, folder = job(tmp_path, "a", language=LanguageSpec("zz", "Nowhere"))
        result = run_job(builder.job_id, folder, tmp_path / "out", KEY)
        assert result.status == "failed"
        assert result.pages[0].error_code == "language_unavailable"

    def test_addon_settings_reach_the_addons(self, tmp_path):
        builder, _folder = job(tmp_path, "a", settings={"pdf": {"licence": "token-1"}})
        manifest = builder.manifest()
        with core_engine(manifest) as engine:
            assert isinstance(engine, CoreEngine)
            db_path = engine._client.db_path
            assert _AddonSettingsStore(db_path, "pdf").get("licence") == "token-1"

    def test_the_job_leaves_nothing_behind(self, tmp_path):
        builder, _folder = job(tmp_path, "a")
        with core_engine(builder.manifest()) as engine:
            folder = engine._client.db_path.parent.parent
            assert folder.exists()
        assert not folder.exists()


class TestBake:
    def test_models_are_downloaded_and_engines_checked(self, tmp_path):
        from vethuq_worker.bake import bake

        models = tmp_path / "models"
        assert bake(models, say=lambda _line: None) == 1
        assert (models / "fake" / "rec-en" / "model.bin").is_file()
        assert fake_pipeline.STATE.engines_created == ["en"]

    def test_a_second_bake_downloads_nothing(self, tmp_path):
        from vethuq_worker.bake import bake

        bake(tmp_path / "m", say=lambda _line: None)
        fake_pipeline.STATE.downloads.clear()
        bake(tmp_path / "m", say=lambda _line: None)
        assert fake_pipeline.STATE.downloads == []

    def test_a_failed_download_fails_the_bake(self, tmp_path):
        import pytest

        from vethuq_worker.bake import BakeError, bake

        fake_pipeline.STATE.download_fails.add("rec-en")
        with pytest.raises(BakeError):
            bake(tmp_path / "m", say=lambda _line: None)

    def test_no_engine_means_no_image(self, tmp_path):
        import pytest

        from vethuq_worker.bake import BakeError, bake

        fake_pipeline.STATE.engine_available = False
        with pytest.raises(BakeError):
            bake(tmp_path / "m", say=lambda _line: None)

    def test_cli_reports_the_outcome(self, tmp_path, capsys):
        from vethuq_worker.cli import main

        assert main(["bake-models", "--models", str(tmp_path / "m")]) == 0
        assert "1 engine(s) ready" in capsys.readouterr().out
        fake_pipeline.STATE.download_fails.add("rec-en")
        assert main(["bake-models", "--models", str(tmp_path / "m2")]) == 1
