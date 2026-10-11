"""A worker-scheduler add-on setting how many files are read at once (`workers` = `auto`)."""

from __future__ import annotations

import sys
import threading
import time

import pytest
from sqlalchemy import select

import tests.fake_pipeline as fp
import vethuq
from vethuq._db import _FileFootprint
from vethuq._indexing import _Indexer
from vethuq._indexing.autoscale import _Governor
from vethuq_addon_api.testing import FakeScheduler


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "QUICK_CHECK_SECONDS", 3600.0)
    monkeypatch.setattr(_Governor, "ASK_SECONDS", 0.02)


@pytest.fixture
def scale(tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.mktemp("scale_addons")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    fp.install(folder, fp.SCALING)
    yield
    fp.FakeScaleAddon.SCALE = None
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
        if name.rsplit(".", 1)[-1] == "autoscale":
            del sys.modules[name]


@pytest.fixture
def client(tmp_path, scale):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    for n in range(6):
        (folder / f"f{n}.pdf").write_text(
            fp.pdf_document(fp.native_page(f"Native text number {n} with many words in it.")),
            encoding="utf-8",
        )
    return folder


def footprints(client):
    with client._db().session() as session:  # noqa: SLF001
        return list(session.scalars(select(_FileFootprint)))


def test_the_scheduler_is_asked_and_footprints_are_kept(client, root):
    fp.FakeScaleAddon.SCALE = scheduler = FakeScheduler(2)
    client.settings.index.set_workers("auto")
    client.index.run(client.sources.create(root).id)
    assert scheduler.plans
    assert all(1 <= plan.ceiling for plan in scheduler.plans)
    assert len(footprints(client)) == 6
    assert all(f.pages == 1 for f in footprints(client))


def test_later_plans_carry_the_history(client, root):
    fp.FakeScaleAddon.SCALE = scheduler = FakeScheduler(1)
    client.settings.index.set_workers("auto")
    client.index.run(client.sources.create(root).id)
    assert len(scheduler.plans[-1].history) >= 1


def test_it_is_not_asked_for_a_fixed_number_of_workers(client, root):
    fp.FakeScaleAddon.SCALE = scheduler = FakeScheduler(1)
    client.settings.index.set_workers(2)
    client.index.run(client.sources.create(root).id)
    assert scheduler.plans == []
    assert footprints(client) == []


def test_without_a_scheduler_the_run_is_unchanged(client, root):
    client.settings.index.set_workers("auto")  # the add-on is installed but returns None
    run = client.index.run(client.sources.create(root).id)
    assert run.files_processed == 6
    assert footprints(client) == []


def test_a_failing_scheduler_falls_back_to_the_static_estimate(client, root):
    class Broken(FakeScheduler):
        def allowed(self, plan):
            raise RuntimeError("boom")

    fp.FakeScaleAddon.SCALE = Broken()
    client.settings.index.set_workers("auto")
    run = client.index.run(client.sources.create(root).id)
    assert run.files_processed == 6


def test_a_scheduler_that_says_zero_never_stops_the_run(client, root):
    fp.FakeScaleAddon.SCALE = FakeScheduler(0)
    client.settings.index.set_workers("auto")
    run = client.index.run(client.sources.create(root).id)
    assert run.files_processed == 6


class TestGovernor:
    def test_files_run_side_by_side_only_up_to_the_answer(self):
        governor = _Governor(None, FakeScheduler(2), ceiling=5)  # type: ignore[arg-type]
        governor._history = lambda: ()  # noqa: SLF001
        peak, now, lock = [0], [0], threading.Lock()

        def job():
            with governor.slot():
                with lock:
                    now[0] += 1
                    peak[0] = max(peak[0], now[0])
                time.sleep(0.03)
                with lock:
                    now[0] -= 1

        threads = [threading.Thread(target=job) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert peak[0] == 2
        assert governor.active == 0

    def test_the_answer_is_capped_at_the_ceiling(self):
        governor = _Governor(None, FakeScheduler(99), ceiling=3)  # type: ignore[arg-type]
        governor._history = lambda: ()  # noqa: SLF001
        assert governor._limit() == 3  # noqa: SLF001
