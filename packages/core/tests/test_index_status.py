"""`index.status()` and the ETA, from the history earlier runs left."""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

import tests.fake_pipeline as fp
import vethuq
from vethuq._db import _DocumentIndex, _IndexRun, _RemoteJob, _UsageDaily
from vethuq._indexing import _Indexer, _Runs
from vethuq.enums import FileStatus, IndexRunStatus, RemoteJobStatus
from vethuq.index import IndexEta, IndexStatus


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(_Indexer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(_Indexer, "POLL_SECONDS", 0.05)


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        yield client


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    return folder


def write(folder, name, *pages):
    path = folder / name
    path.write_text(fp.pdf_document(*pages), encoding="utf-8")
    return path


def db(client):
    return client._db().session()  # noqa: SLF001


def history(client, root, seconds_per_page=2.0):
    """One scanned PDF indexed, and its OCR pass timed at `seconds_per_page`."""
    write(root, "done.pdf", fp.scanned_page("hello from the scan"))
    source = client.sources.create(root)
    client.index.run(source.id)
    with db(client) as session:
        session.execute(
            update(_UsageDaily)
            .where(_UsageDaily.phase != "")
            .values(duration_ms=int(seconds_per_page * 1000))
        )
        session.commit()
    return source


def running(client, source, total, processed, workers=1, tier="local", status=None):
    """A run that is going in this process, with `total - processed` scanned PDFs waiting."""
    with db(client) as session:
        for n in range(total - processed):
            session.add(
                _DocumentIndex(
                    source_id=source.id,
                    file_path=str(source.path) + f"/new{n}.pdf",
                    status=FileStatus.PENDING,
                    size_bytes=1,
                    modified_at="2026-01-01T00:00:00+00:00",
                    discovered_at="2026-01-01T00:00:00+00:00",
                )
            )
        run = _IndexRun(
            source_id=source.id,
            status=status or IndexRunStatus.RUNNING,
            tier=tier,
            total_files=total,
            processed_files=processed,
            workers=workers,
            pid=os.getpid(),
            started_at=datetime.now(UTC).isoformat(),
        )
        session.add(run)
        session.commit()
        run_id = run.id
    _Runs._active.add(run_id)
    return run_id


@pytest.fixture(autouse=True)
def _forget_runs():
    yield
    _Runs._active.clear()


class TestNoRuns:
    def test_none_before_any_run(self, client):
        assert client.index.status() is None

    def test_bad_arguments(self, client):
        with pytest.raises(ValueError):
            client.index.status(timeout=0)
        with pytest.raises(TypeError):
            client.index.status(wait="yes")


class TestAfterARun:
    def test_run_reports_nothing_left(self, client, root):
        write(root, "a.pdf", fp.scanned_page("hello"))
        run = client.index.run(client.sources.create(root).id)
        assert isinstance(run.eta, IndexEta)
        assert (run.eta.seconds, run.eta.remote_seconds, run.eta.complete) == (0, 0, True)
        assert client.index.get(run.id).eta is None  # only `run()` carries it

    def test_status_of_a_finished_run(self, client, root):
        write(root, "a.pdf", fp.scanned_page("hello"))
        run = client.index.run(client.sources.create(root).id)
        status = client.index.status()
        assert isinstance(status, IndexStatus)
        assert status.run.id == run.id and status.run.status is IndexRunStatus.COMPLETED
        assert (status.active, status.remote_jobs_open, status.finished) == (False, 0, True)
        assert status.eta.seconds == 0

    def test_dict_and_json(self, client, root):
        write(root, "a.pdf", fp.scanned_page("hello"))
        client.index.run(client.sources.create(root).id)
        status = client.index.status()
        assert status.to_dict()["eta"]["complete"] is True
        assert status.to_dict()["run"]["eta"] is None
        assert '"finished": true' in status.to_json()


class TestLocalEta:
    def test_files_left_times_the_pages_times_the_pace(self, client, root):
        source = history(client, root, seconds_per_page=2.0)
        running(client, source, total=4, processed=1)  # three scanned PDFs left
        status = client.index.status()
        assert status.active and not status.finished
        assert status.eta.by_file_type == {"pdf": 6}
        assert (status.eta.seconds, status.eta.local_seconds, status.eta.complete) == (6, 6, True)

    def test_workers_share_the_time(self, client, root):
        source = history(client, root, seconds_per_page=2.0)
        running(client, source, total=5, processed=1, workers=2)  # four left, two at a time
        assert client.index.status().eta.seconds == 4

    def test_native_pages_cost_nothing(self, client, root):
        write(root, "n.pdf", fp.native_page("one two three four five six seven"))
        source = client.sources.create(root)
        client.index.run(source.id)
        running(client, source, total=3, processed=0)
        eta = client.index.status().eta
        assert (eta.seconds, eta.complete) == (0, True)  # no OCR pace is needed for them

    def test_a_file_type_never_seen_is_left_out_and_not_complete(self, client, root):
        source = history(client, root)
        run_id = running(client, source, total=2, processed=0)
        with db(client) as session:
            session.get(_IndexRun, run_id).total_files = 3  # the two PDFs and the CSV
            session.add(
                _DocumentIndex(
                    source_id=source.id,
                    file_path=str(root / "x.csv"),
                    status=FileStatus.PENDING,
                    size_bytes=1,
                    modified_at="2026-01-01T00:00:00+00:00",
                    discovered_at="2026-01-01T00:00:00+00:00",
                )
            )
            session.commit()
        eta = client.index.status().eta
        assert eta.complete is False and eta.seconds == 4  # the two PDFs, not the CSV

    def test_the_last_30_days_win_over_all_time(self, client, root):
        source = history(client, root, seconds_per_page=2.0)
        with db(client) as session:
            row = session.scalars(select(_UsageDaily).where(_UsageDaily.phase != "")).first()
            old = datetime.now(UTC) - timedelta(days=90)
            session.add(
                _UsageDaily(
                    day=old.date().isoformat(),
                    source_id=source.id,
                    file_type="pdf",
                    phase="quick",
                    language="en",
                    engine="slow",
                    page_source="ocr",
                    size_bucket="xs",
                    band="high",
                    pages=1,
                    passes=1,
                    duration_ms=60_000,
                )
            )
            session.commit()
            assert row is not None
        running(client, source, total=2, processed=1)
        assert client.index.status().eta.seconds == 2  # not the slow old pace

    def test_an_old_pace_is_used_when_nothing_is_recent(self, client, root):
        source = history(client, root, seconds_per_page=2.0)
        with db(client) as session:
            session.execute(
                update(_UsageDaily).values(
                    day=(datetime.now(UTC) - timedelta(days=90)).date().isoformat()
                )
            )
            session.commit()
        running(client, source, total=2, processed=1)
        assert client.index.status().eta.seconds == 2


class TestRemoteEta:
    def jobs(self, client, run_id, tier="github", took=100.0, open_age=40.0):
        now = datetime.now(UTC)
        with db(client) as session:
            for n in range(2):  # two earlier jobs that took `took` seconds
                started = now - timedelta(days=1, seconds=n)
                session.add(
                    _RemoteJob(
                        run_id=None, tier=tier, wallet=tier, handle="h", images=1,
                        status=RemoteJobStatus.COMPLETED,
                        submitted_at=started.isoformat(),
                        updated_at=started.isoformat(),
                        completed_at=(started + timedelta(seconds=took)).isoformat(),
                    )
                )  # fmt: skip
            if open_age is not None:
                started = now - timedelta(seconds=open_age)
                session.add(
                    _RemoteJob(
                        run_id=run_id, tier=tier, wallet=tier, handle="h", images=1,
                        status=RemoteJobStatus.SUBMITTED,
                        submitted_at=started.isoformat(),
                        updated_at=started.isoformat(),
                    )
                )  # fmt: skip
            session.commit()

    def test_a_job_out_is_expected_back_after_the_usual_time(self, client, root):
        source = history(client, root)
        run_id = running(
            client, source, total=1, processed=1, tier="github",
            status=IndexRunStatus.WAITING_REMOTE,
        )  # fmt: skip
        self.jobs(client, run_id, took=100, open_age=40)
        status = client.index.status()
        assert (status.active, status.remote_jobs_open, status.finished) == (False, 1, False)
        assert status.eta.remote_seconds == pytest.approx(60, abs=3)
        assert status.eta.local_seconds == 0 and status.eta.complete

    def test_a_late_job_is_due_any_moment(self, client, root):
        source = history(client, root)
        run_id = running(
            client, source, total=1, processed=1, tier="github",
            status=IndexRunStatus.WAITING_REMOTE,
        )  # fmt: skip
        self.jobs(client, run_id, took=10, open_age=500)
        assert client.index.status().eta.remote_seconds == 0

    def test_no_history_for_the_tier_is_not_complete(self, client, root):
        source = history(client, root)
        run_id = running(
            client, source, total=1, processed=1, tier="github",
            status=IndexRunStatus.WAITING_REMOTE,
        )  # fmt: skip
        self.jobs(client, run_id, tier="other", open_age=None)
        now = datetime.now(UTC)
        with db(client) as session:
            session.add(
                _RemoteJob(
                    run_id=run_id, tier="github", wallet="github", handle="h", images=1,
                    status=RemoteJobStatus.SUBMITTED,
                    submitted_at=now.isoformat(), updated_at=now.isoformat(),
                )
            )  # fmt: skip
            session.commit()
        eta = client.index.status().eta
        assert eta.complete is False and eta.remote_seconds == 0

    def test_a_run_with_pages_still_to_send_adds_one_more_batch(self, client, root):
        source = history(client, root, seconds_per_page=2.0)
        run_id = running(client, source, total=3, processed=1, tier="github")
        self.jobs(client, run_id, took=100, open_age=None)
        eta = client.index.status().eta
        assert eta.remote_seconds == 100  # a batch is sent at the end and takes the usual time
        assert eta.local_seconds == 0  # the remote tier reads the pages, not this computer


class TestWait:
    def test_waits_for_a_run_going_elsewhere(self, client, root):
        source = history(client, root)
        run_id = running(client, source, total=2, processed=1)

        def finish():
            time.sleep(0.4)
            with db(client) as session:
                session.get(_IndexRun, run_id).status = IndexRunStatus.COMPLETED
                session.commit()
            _Runs._active.discard(run_id)

        thread = threading.Thread(target=finish)
        thread.start()
        started = time.monotonic()
        status = client.index.status(wait=True)
        thread.join()
        assert time.monotonic() - started >= 0.3
        assert status.finished and status.run.status is IndexRunStatus.COMPLETED
        assert status.eta.seconds == 0

    def test_the_timeout_ends_the_wait(self, client, root):
        source = history(client, root)
        running(client, source, total=2, processed=1)
        started = time.monotonic()
        status = client.index.status(wait=True, timeout=0.01)  # 0.6 s
        assert 0.4 < time.monotonic() - started < 5
        assert status.active and not status.finished

    def test_a_run_whose_process_died_is_failed(self, client, root):
        source = history(client, root)
        run_id = running(client, source, total=2, processed=1)
        _Runs._active.discard(run_id)  # nothing is running it any more
        status = client.index.status(wait=True)
        assert status.run.status is IndexRunStatus.FAILED and status.finished
