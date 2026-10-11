"""Fetching the OCR models: once and ahead of time, and a failure said once."""

from __future__ import annotations

import logging
import sys

import pytest

import vethuq
from tests import fake_pipeline as fp
from vethuq._indexing import _Indexer
from vethuq._ocr import _Ocr
from vethuq.enums import FileStatus, IndexRunStatus


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "QUICK_CHECK_SECONDS", 3600.0)


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages):
    (folder / name).write_text(fp.pdf_document(*pages), encoding="utf-8")


def statuses(client, source):
    return {f.name: f.index for f in client.sources.list_files(source.id, detailed=True)}


class TestNoConnection:
    def fail(self):
        fp.STATE.download_fails = {"det-mobile", "rec-en"}

    def test_the_models_are_fetched_once_for_the_whole_run(self, client, root):
        self.fail()
        for n in range(4):
            write(root, f"{n}.pdf", fp.scanned_page(f"scanned words {n}"))
        source = client.sources.create(root)
        run = client.index.run()
        assert run.files_failed == 4
        # The preflight tried; the files then found the failure remembered, not four more tries.
        assert sorted(fp.STATE.downloads) == ["det-mobile", "rec-en"]
        assert all("download the OCR models" in f.error for f in statuses(client, source).values())

    def test_it_is_said_once_up_front(self, client, root, caplog):
        self.fail()
        for n in range(3):
            write(root, f"{n}.pdf", fp.scanned_page(f"scanned words {n}"))
        client.sources.create(root)
        with caplog.at_level(logging.WARNING, logger="vethuq.indexing"):
            client.index.run()
        notes = [r.getMessage() for r in caplog.records if "isn't ready" in r.getMessage()]
        assert len(notes) == 1 and "English" in notes[0] and "download" in notes[0]

    def test_files_with_a_text_layer_still_index(self, client, root):
        self.fail()
        write(root, "n.pdf", fp.native_page("only native words in this one, which is long"))
        (root / "a.txt").write_text("plain text")
        source = client.sources.create(root)
        run = client.index.run()
        assert run.status is IndexRunStatus.COMPLETED and run.files_failed == 0
        assert {f.status for f in statuses(client, source).values()} == {FileStatus.INDEXED}

    def test_the_next_run_tries_again_once_the_wait_is_over(self, client, root, monkeypatch):
        self.fail()
        write(root, "a.pdf", fp.scanned_page("scanned words"))
        source = client.sources.create(root)
        client.index.run()
        assert statuses(client, source)["a.pdf"].status is FileStatus.ERROR
        fp.STATE.download_fails = set()
        monkeypatch.setattr(_Ocr, "RETRY_SECONDS", 0.0)
        client.index.restart()
        assert statuses(client, source)["a.pdf"].status is FileStatus.INDEXED

    def test_a_failure_is_remembered_only_for_a_while(self, client, root):
        self.fail()
        write(root, "a.pdf", fp.scanned_page("scanned words"))
        client.sources.create(root)
        client.index.run()
        before = len(fp.STATE.downloads)
        fp.STATE.download_fails = set()
        client.index.restart()  # still inside the wait: not tried again
        assert len(fp.STATE.downloads) == before


class TestAPhaseWhoseModelsAreMissing:
    @pytest.fixture
    def phases(self, tmp_path_factory, monkeypatch):
        folder = tmp_path_factory.mktemp("phase_addons")
        monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
        fp.install(folder, {"ocr-moderate": fp.DEEPER["ocr-moderate"]})
        yield
        for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
            if name.rsplit(".", 1)[-1] == "ocr_moderate":
                del sys.modules[name]

    def test_it_is_said_once_not_once_per_page(self, phases, client, root, caplog):
        write(root, "a.pdf", *[fp.scanned_page(f"scanned words {n}") for n in range(6)])
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        # The mobile models are fine; the server ones (for moderate) cannot be fetched.
        original = fp.FakeProvider.required_models

        def required(self, language, profile):
            specs = original(self, language, profile)
            if profile == "server":
                fp.STATE.download_fails.add("det-server")
                return [*specs, type(specs[0])("det-server", "detection", shared=True)]
            return specs

        fp.FakeProvider.required_models = required
        try:
            with caplog.at_level(logging.WARNING, logger="vethuq.indexing"):
                run = client.index.run()
        finally:
            fp.FakeProvider.required_models = original
        assert run.status is IndexRunStatus.COMPLETED
        notes = [
            r.getMessage()
            for r in caplog.records
            if "moderate OCR phase can't read" in r.getMessage()
        ]
        assert len(notes) == 1
        assert fp.STATE.downloads.count("det-server") == 1  # tried once, not for each page
        assert len(client.search.run("scanned").matches) >= 1  # the quick pass is untouched
