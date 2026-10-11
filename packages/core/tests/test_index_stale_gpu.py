"""The stale-lock setting and `index.clear_stale()`, and the GPU setting for OCR engines."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import tests.fake_pipeline as fp
import vethuq
from vethuq import errors
from vethuq._db import _IndexRun
from vethuq.enums import IndexRunStatus

DEAD_PID = 2**22 + 12345


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.pdf").write_text(fp.pdf_document(fp.scanned_page("hello scan")))
        client.sources.create(folder)
        yield client


def leave_a_run(client):
    with client._db().session() as session:  # noqa: SLF001
        session.add(
            _IndexRun(
                status=IndexRunStatus.RUNNING,
                pid=DEAD_PID,
                started_at=datetime.now(UTC).isoformat(),
            )
        )


class TestStaleLock:
    def test_auto_is_the_default_and_clears_the_run(self, client):
        assert client.settings.index.get_stale_lock() == "auto"
        leave_a_run(client)
        assert client.index.run().status is IndexRunStatus.COMPLETED

    def test_enable_behaves_like_auto(self, client):
        client.settings.index.set_stale_lock("enable")
        leave_a_run(client)
        assert client.index.run().status is IndexRunStatus.COMPLETED

    def test_disable_refuses_to_start_and_says_how_to_clear_it(self, client):
        client.settings.index.set_stale_lock("disable")
        leave_a_run(client)
        with pytest.raises(errors.IndexAlreadyRunningError, match="left behind") as caught:
            client.index.run()
        assert "clear_stale" in str(caught.value) or "clear_stale" in repr(caught.value.__dict__)

    def test_clear_stale_then_a_run_starts(self, client):
        client.settings.index.set_stale_lock("disable")
        leave_a_run(client)
        assert client.index.clear_stale() == 1
        assert client.index.clear_stale() == 0
        assert client.index.run().status is IndexRunStatus.COMPLETED
        failed = [r for r in client.index.history() if r.status is IndexRunStatus.FAILED]
        assert len(failed) == 1 and "ended before" in failed[0].error

    def test_a_run_going_in_this_process_is_never_cleared(self, client):
        from vethuq._indexing import _Runs

        with client._db().session() as session:  # noqa: SLF001
            _Runs.begin(session, None, None, 1)
        try:
            assert client.index.clear_stale() == 0
            with pytest.raises(errors.IndexAlreadyRunningError):
                client.index.run()
        finally:
            _Runs.end(1)

    def test_bad_values_are_refused_and_reset_restores_auto(self, client):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.index.set_stale_lock("sometimes")
        client.settings.index.set_stale_lock("disable")
        client.settings.index.reset_stale_lock()
        assert client.settings.index.get_stale_lock() == "auto"


class TestGpu:
    def test_off_by_default_and_settable(self, client):
        assert client.settings.ocr.get_gpu() is False
        assert client.settings.ocr.set_gpu(True) is True
        assert client.settings.ocr.get_gpu() is True
        client.settings.ocr.reset_gpu()
        assert client.settings.ocr.get_gpu() is False

    @pytest.mark.parametrize("value", ["yes", 1, None])
    def test_only_a_boolean_is_accepted(self, client, value):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.ocr.set_gpu(value)

    def test_the_engine_is_asked_for_the_gpu_and_falls_back_to_the_cpu(self, client, monkeypatch):
        from vethuq_addon_api import AddonError

        provider = client._runtime().provider("mobile")  # noqa: SLF001
        calls = []
        real = type(provider).create

        def create(self, language, profile, models_dir, use_gpu=False):
            calls.append(use_gpu)
            if use_gpu:
                raise AddonError("no GPU here")
            return real(self, language, profile, models_dir, use_gpu)

        monkeypatch.setattr(type(provider), "create", create)
        client.settings.ocr.set_gpu(True)
        languages = client._manager().language_specs()  # noqa: SLF001
        engine, _phase = client._runtime().engine(languages[0])  # noqa: SLF001
        assert engine is not None and calls == [True, False]
