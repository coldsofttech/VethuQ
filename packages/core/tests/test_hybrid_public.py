"""The hybrid tier: local first; big pages (and chosen OCR phases) go to GitHub; a page GitHub
can't take is read here."""

from __future__ import annotations

import sys

import pytest

import vethuq
from tests import fake_pipeline as fp
from tests import fake_tiers as ft
from vethuq._indexing import _Indexer
from vethuq._tiers import _Router
from vethuq.enums import FileStatus, IndexRunStatus, RemoteJobStatus
from vethuq_addon_api import JobState
from vethuq_addon_api.testing import FakeExecutor


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "POLL_SECONDS", 0.01)


@pytest.fixture
def remote(tmp_path_factory, monkeypatch):
    """The tier add-on with an asynchronous `github` executor the test controls."""
    ft.reset()
    folder = tmp_path_factory.mktemp("hybrid_addon")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    ft.install(folder)
    ft.STATE.github_executor = FakeExecutor(
        default="read on github", asynchronous=True, state=JobState.RUNNING
    )
    yield ft.STATE.github_executor
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.github")]:
        del sys.modules[name]


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages):
    (folder / name).write_text(fp.pdf_document(*pages), encoding="utf-8")


def spent(client, wallet):
    charges = client.credits.history(wallet=wallet, kind="charge")
    refunds = client.credits.history(wallet=wallet, kind="refund")
    return sum(abs(e.amount) for e in charges) - sum(abs(e.amount) for e in refunds)


class TestRouter:
    def test_big_pages_go_away(self):
        router = _Router(2.0)
        assert not router.remote(1.0) and not router.remote(1.99) and router.remote(2.0)

    def test_zero_turns_the_size_rule_off(self):
        assert not _Router(0).remote(50.0)

    def test_chosen_phases_go_away(self):
        router = _Router(0, ("deep",))
        assert router.remote(1.0, "deep") and not router.remote(1.0, "quick")
        assert _Router(2.0, ("moderate",)).remote(1.0, "moderate")


class TestRouting:
    def test_big_pages_are_sent_and_small_ones_stay(self, remote, client, root):
        write(root, "mixed.pdf", fp.scanned_page(), fp.scanned_page(**fp.A3), fp.native_page())
        source = client.sources.create(root)
        run = client.index.run(tier="hybrid")
        assert run.tier == "hybrid" and run.status is IndexRunStatus.WAITING_REMOTE
        (job,) = client.index.jobs()
        assert (job.tier, job.images) == ("github", 1)  # only the A3 page
        assert [r.key for r in remote.seen] == ["d1.l1.2:0"]  # page 2 only; page 1 was read here
        assert spent(client, "local") > 0 and spent(client, "github") > 0
        (file,) = client.sources.list_files(source.id, detailed=True)
        assert file.index.status is not FileStatus.INDEXED  # one page is still away

    def test_collecting_finishes_the_file(self, remote, client, root):
        write(root, "mixed.pdf", fp.scanned_page(), fp.scanned_page(**fp.A3))
        source = client.sources.create(root)
        client.index.run(tier="hybrid")
        remote.state = JobState.DONE
        client.index.collect()
        (file,) = client.sources.list_files(source.id, detailed=True)
        assert file.index.status is FileStatus.INDEXED
        assert client.index.jobs()[0].status is RemoteJobStatus.COMPLETED

    def test_a_document_of_small_pages_never_leaves(self, remote, client, root):
        write(root, "small.pdf", fp.scanned_page(), fp.scanned_page())
        client.sources.create(root)
        run = client.index.run(tier="hybrid")
        assert run.status is IndexRunStatus.COMPLETED
        assert client.index.jobs() == [] and spent(client, "github") == 0

    def test_the_size_rule_can_be_turned_off(self, remote, client, root):
        write(root, "big.pdf", fp.scanned_page(**fp.A3))
        client.sources.create(root)
        client.settings.tiers.set_min_size_factor(0)
        assert client.index.run(tier="hybrid").status is IndexRunStatus.COMPLETED
        assert client.index.jobs() == []

    def test_a_lower_threshold_sends_more(self, remote, client, root):
        write(root, "a4.pdf", fp.scanned_page())
        client.sources.create(root)
        client.settings.tiers.set_min_size_factor(1)
        assert client.index.run(tier="hybrid").status is IndexRunStatus.WAITING_REMOTE

    def test_native_pages_are_never_sent(self, remote, client, root):
        write(root, "n.pdf", fp.native_page(**fp.A3))
        client.sources.create(root)
        assert client.index.run(tier="hybrid").status is IndexRunStatus.COMPLETED
        assert client.index.jobs() == []


class TestFallback:
    def test_a_page_github_cannot_pay_for_is_read_here(self, remote, client, root):
        write(root, "big.pdf", fp.scanned_page(**fp.A3))
        source = client.sources.create(root)
        client._credit_engine().policy = lambda: {
            "wallets": {"github": {"daily_private": 0, "starter": 0, "grace": 0}}
        }
        run = client.index.run(tier="hybrid")
        assert run.status is IndexRunStatus.COMPLETED
        assert client.index.jobs() == [] and spent(client, "github") == 0
        assert spent(client, "local") > 0
        (file,) = client.sources.list_files(source.id, detailed=True)
        assert file.index.status is FileStatus.INDEXED

    def test_local_credits_running_out_still_pauses_the_run(self, remote, client, root):
        write(root, "a.pdf", fp.scanned_page(), fp.scanned_page(), fp.scanned_page())
        client.sources.create(root)
        client._credit_engine().policy = lambda: {
            "wallets": {"local": {"daily": 0, "starter": 0, "grace": 0}}
        }
        run = client.index.run(tier="hybrid")
        assert run.status is IndexRunStatus.WAITING_CREDITS


class TestAvailability:
    def test_hybrid_is_listed_available_with_github(self, remote, client):
        info = client.tiers.get("hybrid")
        assert info.available and info.remote and info.wallet == "local"

    def test_hybrid_follows_github(self, remote, client):
        ft.STATE.github_available = False
        ft.STATE.github_reason = "no runner"
        info = client.tiers.get("hybrid")
        assert not info.available and "no runner" in info.reason
