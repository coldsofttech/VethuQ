"""The deeper OCR phases (moderate, deep): pages read again at other angles."""

from __future__ import annotations

import logging
import sys

import pytest
from sqlalchemy import select

import vethuq
from tests import fake_pipeline as fp
from tests import fake_tiers as ft
from vethuq import errors
from vethuq._db import _PdfPage, _PdfPagePhase, _RemoteJobPage
from vethuq._indexing import _Indexer
from vethuq.enums import IndexRunStatus, RemoteJobStatus
from vethuq_addon_api import JobState
from vethuq_addon_api.testing import FakeExecutor

DEEP_ANGLES = [a for a in range(15, 360, 15) if a % 90]


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(_Indexer, "QUICK_CHECK_SECONDS", 3600.0)


@pytest.fixture
def phases(tmp_path_factory, monkeypatch):
    """The moderate and deep phase add-ons installed."""
    folder = tmp_path_factory.mktemp("phase_addons")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    fp.install(folder, fp.DEEPER)
    yield
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
        if name.rsplit(".", 1)[-1] in {"ocr_moderate", "ocr_deep"}:
            del sys.modules[name]


@pytest.fixture
def moderate_only(tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.mktemp("moderate_addon")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    fp.install(folder, {"ocr-moderate": fp.DEEPER["ocr-moderate"]})
    yield
    for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
        if name.rsplit(".", 1)[-1] == "ocr_moderate":
            del sys.modules[name]


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


def rows(client, model):
    with client._db().session() as session:
        return list(session.scalars(select(model)))


def text(client, number=1):
    return next(p.text for p in rows(client, _PdfPage) if p.page_number == number)


class TestTheSetting:
    def test_quick_unless_changed(self, client):
        assert client.settings.ocr.get_engine() == "quick"

    def test_set_and_reset(self, client):
        assert client.settings.ocr.set_engine(" Deep ") == "deep"
        assert client.settings.ocr.get_engine() == "deep"
        client.settings.ocr.reset_engine()
        assert client.settings.ocr.get_engine() == "quick"

    def test_anything_else_is_refused(self, client):
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.ocr.set_engine("turbo")
        with pytest.raises(errors.InvalidSettingValueError):
            client.settings.ocr.set_engine(3)


class TestQuickIsTheDefault:
    def test_nothing_is_turned_unless_the_engine_asks(self, phases, client, root):
        write(root, "s.pdf", fp.at_angles(fp.scanned_page("upright words"), a90="sideways"))
        client.sources.create(root)
        run = client.index.run()
        assert text(client) == "upright words"
        assert fp.STATE.angle_calls == [] and rows(client, _PdfPagePhase) == []
        assert run.credits_charged == 1.0

    def test_the_phases_are_listed(self, phases, client):
        found = {p.id: p for p in client.ocr.phases.list()}
        assert found["moderate"].angles == (90, 180, 270)
        assert found["deep"].angles == tuple(DEEP_ANGLES)
        assert found["moderate"].profile == found["deep"].profile == "server"


class TestModerate:
    def test_a_scanned_page_is_read_at_the_right_angles_and_the_text_merged(
        self, phases, client, root
    ):
        page = fp.at_angles(
            fp.scanned_page("upright words"), a90="sideways label", a270="other side"
        )
        write(root, "s.pdf", page)
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        run = client.index.run()
        assert run.status is IndexRunStatus.COMPLETED
        assert [a for _, a in fp.STATE.angle_calls] == [90, 180, 270]
        assert text(client) == "upright words\nsideways label\nother side"
        (row,) = rows(client, _PdfPagePhase)
        assert (row.phase, row.angles, row.region_count, row.lines_added) == (
            "moderate",
            "90,180,270",
            1,
            2,
        )

    def test_it_is_charged_per_rotated_pass(self, phases, client, root):
        write(root, "s.pdf", fp.scanned_page("upright words"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        run = client.index.run()
        assert run.credits_charged == pytest.approx(1.0 + 3 * 0.8)  # quick, then 3 rotated reads
        assert run.ocr_pages == 1  # the page is one page, however often it is read
        ledger = [e for e in client.credits.history(kind="charge")]
        assert {e.phase for e in ledger} == {"quick", "moderate"}

    def test_a_second_run_reads_nothing_again(self, phases, client, root):
        write(root, "s.pdf", fp.scanned_page("upright words"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        before = len(fp.STATE.ocr_calls)
        run = client.index.run()
        assert len(fp.STATE.ocr_calls) == before and run.credits_charged == 0

    def test_native_pages_and_files_are_left_alone(self, phases, client, root):
        write(root, "n.pdf", fp.native_page("a page that is all native text, and long enough"))
        (root / "a.txt").write_text("plain words")
        (root / "b.csv").write_text("a,b\n1,2\n")
        client.sources.create(root)
        client.settings.ocr.set_engine("deep")
        client.index.run()
        assert fp.STATE.angle_calls == [] and rows(client, _PdfPagePhase) == []

    def test_only_the_images_of_a_mixed_page_are_turned(self, phases, client, root):
        page = fp.mixed_page("Native text with enough words in it.", "first image")
        page["region_ocr_at"] = [{"180": "upside down caption"}]
        write(root, "m.pdf", page)
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        assert [call[1][0] for call in fp.STATE.ocr_calls] == ["region"] * 4
        assert "upside down caption" in text(client)
        assert text(client).startswith("Native text with enough words in it.")

    def test_a_rotated_line_that_is_not_confident_is_dropped(self, phases, client, root):
        write(root, "s.pdf", fp.at_angles(fp.scanned_page("upright", confidence=0.4), a90="noise"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        assert text(client) == "upright"

    def test_a_line_already_there_is_not_added_and_a_longer_one_replaces_it(
        self, phases, client, root
    ):
        page = fp.at_angles(
            fp.scanned_page("Invoice\nTotal due"), a90="invoice", a180="Total due: 40 euro"
        )
        write(root, "s.pdf", page)
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        assert text(client) == "Invoice\nTotal due: 40 euro"


class TestDeep:
    def test_moderate_goes_before_deep_and_deep_reads_the_other_angles(self, phases, client, root):
        page = fp.at_angles(fp.scanned_page("upright"), a90="sideways", a30="slanted stamp")
        write(root, "s.pdf", page)
        client.sources.create(root)
        client.settings.ocr.set_engine("deep")
        run = client.index.run()
        angles = [a for _, a in fp.STATE.angle_calls]
        assert angles == [90, 180, 270, *DEEP_ANGLES]
        assert text(client) == "upright\nsideways\nslanted stamp"
        assert {r.phase for r in rows(client, _PdfPagePhase)} == {"moderate", "deep"}
        assert run.credits_charged == pytest.approx(1.0 + 3 * 0.8 + 20 * 0.8)

    def test_a_phase_whose_add_on_is_missing_is_skipped_with_a_warning(
        self, moderate_only, client, root, caplog
    ):
        write(root, "s.pdf", fp.at_angles(fp.scanned_page("upright"), a90="sideways"))
        client.sources.create(root)
        client.settings.ocr.set_engine("deep")
        with caplog.at_level(logging.WARNING, logger="vethuq.indexing"):
            client.index.run()
        assert [a for _, a in fp.STATE.angle_calls] == [90, 180, 270]
        assert any("deep OCR phase is not installed" in r.getMessage() for r in caplog.records)

    def test_nothing_deeper_installed(self, client, root, caplog):
        write(root, "s.pdf", fp.scanned_page("upright"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        with caplog.at_level(logging.WARNING, logger="vethuq.indexing"):
            run = client.index.run()
        assert run.status is IndexRunStatus.COMPLETED and fp.STATE.angle_calls == []
        assert any("moderate OCR phase is not installed" in r.getMessage() for r in caplog.records)

    def test_going_deeper_later_only_reads_what_is_new(self, phases, client, root):
        write(root, "s.pdf", fp.at_angles(fp.scanned_page("upright"), a45="diagonal"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        assert text(client) == "upright"
        fp.STATE.angle_calls.clear()
        client.settings.ocr.set_engine("deep")
        client.index.run()
        assert [a for _, a in fp.STATE.angle_calls] == DEEP_ANGLES  # not the right angles again
        assert text(client) == "upright\ndiagonal"


class TestQuickComesFirst:
    def test_a_new_file_is_read_quick_before_the_deeper_phases_go_on(
        self, phases, client, root, monkeypatch
    ):
        write(root, "a.pdf", *[fp.scanned_page(f"page {n}") for n in range(1, 9)])
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        monkeypatch.setattr(_Indexer, "QUICK_CHECK_SECONDS", 0.0)
        created = []
        original = fp.FakeEngine.recognize

        def recognize(self, image, angle=0):
            if angle and not created:  # the first rotated read: a file arrives
                write(root, "late.pdf", fp.scanned_page("late arrival"))
                created.append(len(fp.STATE.ocr_calls))
            return original(self, image, angle)

        monkeypatch.setattr(fp.FakeEngine, "recognize", recognize)
        client.index.run()
        late = [i for i, c in enumerate(fp.STATE.ocr_calls) if c[1][1] == "late arrival"]
        pages = [i for i, c in enumerate(fp.STATE.ocr_calls) if c[1][1] == "page 8"]
        assert created and late
        # The late file was read (quick) while page 8 was still waiting for its moderate read.
        assert created[0] <= late[0] < pages[-1]
        names = {f.name: f.index.status.value for f in client.sources.list_files(1, detailed=True)}
        assert names["late.pdf"] == "indexed"
        assert client.index.get(1).files_total == 2


class TestMarkdownPictures:
    @pytest.fixture
    def png(self, tmp_path_factory, monkeypatch):
        folder = tmp_path_factory.mktemp("png_addon")
        monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
        fp.install(folder, {"png": ("vethuq_addon_png", "FakePngAddon")})
        yield
        for name in [n for n in sys.modules if n.startswith("vethuq.addons.")]:
            if name.rsplit(".", 1)[-1] == "png":
                del sys.modules[name]

    def make(self, root):
        (root / "door.png").write_text("RED DOOR", encoding="utf-8")
        (root / "c.md").write_text("# Doors\n\nA page about doors.\n\n![d](door.png)\n")

    def test_quick_leaves_the_picture_alone(self, phases, png, client, root):
        self.make(root)
        client.sources.create(root)
        client.index.run()
        md = next(p for p in rows(client, _PdfPage) if "doors" in p.text)
        assert "RED DOOR" not in md.text and md.deepen_from == "moderate"

    def test_moderate_reads_it_upright_and_at_the_right_angles(self, phases, png, client, root):
        self.make(root)
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run()
        md = next(p for p in rows(client, _PdfPage) if "doors" in p.text)
        assert "RED DOOR" in md.text and md.source.value == "mixed"
        (row,) = [r for r in rows(client, _PdfPagePhase) if r.page_id == md.id]
        assert row.angles == "0,90,180,270"

    def test_deep_adds_the_other_angles_but_not_upright_again(self, phases, png, client, root):
        self.make(root)
        client.sources.create(root)
        client.settings.ocr.set_engine("deep")
        client.index.run()
        md = next(p for p in rows(client, _PdfPage) if "doors" in p.text)
        deep = next(
            r for r in rows(client, _PdfPagePhase) if r.page_id == md.id and r.phase == "deep"
        )
        assert deep.angles == ",".join(str(a) for a in sorted(DEEP_ANGLES))

    def test_without_an_add_on_for_the_format_nothing_is_recorded_and_it_warns(
        self, phases, client, root, caplog
    ):
        self.make(root)
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        with caplog.at_level(logging.WARNING, logger="vethuq.indexing"):
            run = client.index.run()
        assert run.status is IndexRunStatus.COMPLETED
        assert rows(client, _PdfPagePhase) == []  # retried once an add-on reads PNG
        assert any("door.png" in r.getMessage() for r in caplog.records)
        assert "doors" in text(client)


class TestOnARemoteTier:
    @pytest.fixture
    def remote(self, tmp_path_factory, monkeypatch):
        ft.reset()
        folder = tmp_path_factory.mktemp("remote_addon")
        monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
        ft.install(folder)
        ft.STATE.github_executor = FakeExecutor(
            default="found remotely", asynchronous=True, state=JobState.DONE
        )
        yield ft.STATE.github_executor
        for name in [n for n in sys.modules if n.startswith("vethuq.addons.github")]:
            del sys.modules[name]

    def test_the_rotated_reads_are_sent_and_merged_when_they_come_back(
        self, phases, remote, client, root
    ):
        write(root, "s.pdf", fp.scanned_page("upright"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        client.index.run(tier="github")  # the quick page goes away and comes back
        assert "found remotely" in text(client)
        remote.state = JobState.RUNNING  # the tier is slow this time
        run = client.index.run(tier="github")  # moderate goes away too
        assert run.status is IndexRunStatus.WAITING_REMOTE
        assert (
            client.index.status().eta.remote_seconds == 0 and client.index.status().active is False
        )
        sent = [r for r in remote.seen if r.phase == "moderate"]
        assert [r.angle for r in sent] == [90, 180, 270]
        assert len({id(r.image) for r in sent}) == 1  # one image, read at three angles
        assert {r.phase for r in remote.seen} == {"quick", "moderate"}
        images = rows(client, _RemoteJobPage)
        assert {(i.phase, i.angle) for i in images if i.phase == "moderate"} == {
            ("moderate", 90), ("moderate", 180), ("moderate", 270),
        }  # fmt: skip
        remote.state = JobState.DONE
        client.index.collect()
        (row,) = rows(client, _PdfPagePhase)
        assert (row.phase, row.angles) == ("moderate", "90,180,270")
        assert all(j.status is RemoteJobStatus.COMPLETED for j in client.index.jobs())
        assert client.index.status().eta.seconds == 0

    def test_a_job_that_fails_gives_the_credits_back_and_the_page_is_tried_again(
        self, phases, remote, client, root
    ):
        write(root, "s.pdf", fp.scanned_page("upright"))
        client.sources.create(root)
        client.index.run(tier="github")
        client.settings.ocr.set_engine("moderate")
        remote.state = JobState.FAILED
        client.index.run(tier="github")
        assert rows(client, _PdfPagePhase) == []
        assert client.credits.balance("github").daily == 19  # only the quick page stays paid
        remote.state = JobState.DONE
        client.index.run(tier="github")
        assert len(rows(client, _PdfPagePhase)) == 1


class TestEta:
    """The time left counts the deeper phases the engine setting reaches."""

    def history(self, client, phase="moderate", seconds_per_pass=2.0, passes=3):
        from datetime import UTC, datetime

        from vethuq._db import _UsageDaily

        with client._db().session() as session:
            session.add(
                _UsageDaily(
                    day=datetime.now(UTC).date().isoformat(),
                    source_id=None,
                    file_type="pdf",
                    phase=phase,
                    language="en",
                    engine="fake",
                    page_source="ocr",
                    size_bucket="s",
                    band="high",
                    pages=1,
                    passes=passes,
                    duration_ms=int(seconds_per_pass * 1000 * passes),
                )
            )

    def running(self, client):
        import os
        from datetime import UTC, datetime

        from vethuq._db import _IndexRun
        from vethuq._indexing import _Runs

        with client._db().session() as session:
            run = _IndexRun(
                status=IndexRunStatus.RUNNING,
                tier="local",
                total_files=1,
                processed_files=1,
                workers=1,
                pid=os.getpid(),
                started_at=datetime.now(UTC).isoformat(),
            )
            session.add(run)
            session.flush()
            _Runs._active.add(run.id)
            return run.id

    def test_pages_waiting_for_moderate_times_its_angles_times_its_pace(self, phases, client, root):
        write(root, "a.pdf", fp.scanned_page("one"), fp.scanned_page("two"))
        client.sources.create(root)
        client.index.run()  # quick only
        self.history(client)
        client.settings.ocr.set_engine("moderate")
        self.running(client)
        eta = client.index.status().eta
        assert eta.by_phase == {"moderate": 12}  # 2 pages x 3 angles x 2 s
        assert (eta.local_seconds, eta.seconds, eta.complete) == (12, 12, True)

    def test_deep_is_counted_when_the_engine_reaches_it(self, phases, client, root):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        client.index.run()
        self.history(client, "moderate", 1.0)
        self.history(client, "deep", 2.0, passes=20)
        client.settings.ocr.set_engine("deep")
        self.running(client)
        eta = client.index.status().eta
        assert eta.by_phase == {"moderate": 3, "deep": 40}

    def test_a_phase_that_never_ran_is_not_complete(self, phases, client, root):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        client.index.run()
        client.settings.ocr.set_engine("moderate")
        self.running(client)
        eta = client.index.status().eta
        assert eta.seconds == 0 and eta.complete is False

    def test_native_pages_and_the_quick_engine_add_nothing(self, phases, client, root):
        write(root, "a.pdf", fp.scanned_page("one"))
        client.sources.create(root)
        client.index.run()
        self.history(client)
        self.running(client)
        assert client.index.status().eta.by_phase == {}  # the engine is still quick

    def test_the_quick_pace_ignores_the_rotated_reads(self, phases, client, root):
        from vethuq._indexing.eta import _Eta

        self.history(client, "quick", 1.0, passes=1)
        self.history(client, "moderate", 50.0, passes=3)
        with client._db().session() as session:
            assert _Eta(None)._seconds_per_ocr_page(session) == {"pdf": 1.0}


class TestRunningOut:
    def test_a_phase_that_cannot_be_paid_for_pauses_the_run_and_loses_nothing(
        self, phases, client, root
    ):
        client._credit_engine().policy = lambda: {
            "wallets": {"local": {"daily": 2, "starter": 0}},
            "grace_percent": 0,
        }
        write(root, "a.pdf", fp.at_angles(fp.scanned_page("upright"), a90="sideways"))
        client.sources.create(root)
        client.settings.ocr.set_engine("moderate")
        run = client.index.run()
        # Quick cost 1 of the 2 credits; the three rotated reads (2.4) do not fit.
        assert run.status is IndexRunStatus.WAITING_CREDITS
        assert text(client) == "upright" and rows(client, _PdfPagePhase) == []
        assert run.credits_charged == 1.0 and fp.STATE.angle_calls == []
