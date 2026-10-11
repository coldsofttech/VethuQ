"""The worker-scheduling contract."""

from __future__ import annotations

from vethuq_addon_api import Addon, Footprint, Manifest, WorkerScheduler, WorkPlan
from vethuq_addon_api.testing import FakeHost, FakeScheduler


def test_an_addon_offers_no_scheduler_by_default(tmp_path):
    class Plain(Addon):
        manifest = Manifest("plain", "plain", "1.0.0")

    assert Plain(FakeHost(tmp_path / "db")).worker_scheduler() is None


def test_the_fake_scheduler_repeats_its_last_answer_and_keeps_the_plans():
    scheduler = FakeScheduler(3, 1)
    plan = WorkPlan(ceiling=4, active=0, queued=5, history=(Footprint(10, 2, 0.5, 1),))
    assert isinstance(scheduler, WorkerScheduler)
    assert [scheduler.allowed(plan) for _ in range(3)] == [3, 1, 1]
    assert scheduler.plans[0].history[0].pages == 2
