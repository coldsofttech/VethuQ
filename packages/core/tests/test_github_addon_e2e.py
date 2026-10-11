"""The real GitHub add-on (from the premium repository, if it is checked out next to this one)
driven by a real index run: core stages and sends the pages, the add-on seals and uploads them,
a fake runner plays the workflow with the real worker, and core imports the answers. Only
api.github.com and the OCR engine are faked."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy
import pytest

import vethuq
from tests import fake_pipeline as fp
from vethuq._indexing import _Indexer
from vethuq.enums import FileStatus, IndexRunStatus
from vethuq_addon_api.testing import FakeExecutor
from vethuq_worker import StaticEngine

PREMIUM = (
    Path(__file__).resolve().parents[4]
    / "VethuQ-premium"
    / "packages"
    / "add-ons"
    / "tiers"
    / "github"
)
pytestmark = pytest.mark.skipif(
    not PREMIUM.is_dir(), reason="VethuQ-premium isn't checked out next to this repository"
)


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "POLL_SECONDS", 0.01)


@pytest.fixture
def addon(tmp_path_factory, monkeypatch):
    """Make the premium GitHub add-on look installed, with its tests' fake GitHub."""
    folder = tmp_path_factory.mktemp("github_addon")
    dist = folder / "vethuq_addon_github-0.1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: vethuq_addon_github\nVersion: 0.1.0\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text(
        "[vethuq.addons]\ngithub = vethuq_addon_github:GithubAddon\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        sys, "path", [str(folder), str(PREMIUM / "src"), str(PREMIUM / "tests"), *sys.path]
    )
    yield
    for name in [n for n in sys.modules if n.startswith(("vethuq_addon_github", "github_support"))]:
        del sys.modules[name]
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.github")]:
        del sys.modules[name]


@pytest.fixture
def fake(addon, monkeypatch):
    from github_support import FakeGitHub
    from vethuq_addon_github._api import _Api

    github = FakeGitHub()
    monkeypatch.setattr(_Api, "transport_factory", staticmethod(lambda: github))
    monkeypatch.setenv("VETHUQ_GITHUB_TOKEN", "ghp_good")
    return github


@pytest.fixture
def client(fake, tmp_path, monkeypatch):
    # The fake reader renders tuples; the real job protocol sends pictures.
    monkeypatch.setattr(fp, "self_render", lambda page, region: numpy.full((20, 30, 3), 9, "uint8"))
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        yield client


def test_a_run_through_the_real_addon(client, fake, tmp_path):
    from vethuq.addons.github import GitHub

    GitHub(client).setup("runner")
    assert {t.id: t.available for t in client.tiers.list()}["github"] is True

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "scan.pdf").write_text(fp.pdf_document(fp.scanned_page(), fp.scanned_page()))
    (docs / "text.pdf").write_text(fp.pdf_document(fp.native_page()))
    source = client.sources.create(docs)

    run = client.index.run(tier="github")
    assert run.status is IndexRunStatus.WAITING_REMOTE
    (job,) = client.index.jobs()
    assert job.tier == "github" and job.images == 2

    (run_id,) = fake.repo("octo/runner")["runs"]
    engine = StaticEngine(FakeExecutor(default="read on the runner"), [_en()])
    fake.execute("octo/runner", run_id, engine, tmp_path)

    client.index.collect()
    names = {f.name: f.index.status for f in client.sources.list_files(source.id, detailed=True)}
    assert names == {"scan.pdf": FileStatus.INDEXED, "text.pdf": FileStatus.INDEXED}
    assert fake.repo("octo/runner")["releases"] == {}


def _en():
    from vethuq_addon_api import LanguageSpec

    return LanguageSpec("en", "English", default=True)


def test_hybrid_sends_only_the_big_page_through_the_real_addon(client, fake, tmp_path):
    from vethuq.addons.github import GitHub

    GitHub(client).setup("runner")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "mixed.pdf").write_text(fp.pdf_document(fp.scanned_page(), fp.scanned_page(**fp.A3)))
    source = client.sources.create(docs)

    run = client.index.run(tier="hybrid")
    assert run.tier == "hybrid" and run.status is IndexRunStatus.WAITING_REMOTE
    (job,) = client.index.jobs()
    assert (job.tier, job.images) == ("github", 1)

    (run_id,) = fake.repo("octo/runner")["runs"]
    engine = StaticEngine(FakeExecutor(default="read on the runner"), [_en()])
    fake.execute("octo/runner", run_id, engine, tmp_path)
    client.index.collect()
    (file,) = client.sources.list_files(source.id, detailed=True)
    assert file.index.status is FileStatus.INDEXED
