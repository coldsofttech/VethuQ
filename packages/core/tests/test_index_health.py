"""A run's heartbeat and stall report, the integrity check after a left-behind run, and the
search-index rebuild that refuses to run beside an index run."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

import tests.fake_pipeline as fp
import vethuq
from vethuq import errors
from vethuq._db import IntegrityCheckResult, _IndexRun, _IntegrityCheck
from vethuq._indexing import _Indexer, _Runs
from vethuq.enums import IndexRunStatus
from vethuq.search import SearchIndexRebuildResult


@pytest.fixture
def client(tmp_path):
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        client.settings.index.set_stability_check_seconds(0)
        client.settings.index.set_retry_attempts(0)
        client.settings.index.set_workers(0)
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.pdf").write_text(fp.pdf_document(fp.native_page()))
        client.sources.create(folder)
        yield client


def leave_a_run(client):
    with client._db().session() as session:  # noqa: SLF001
        session.add(
            _IndexRun(
                status=IndexRunStatus.RUNNING,
                pid=2**22 + 12345,
                started_at=datetime.now(UTC).isoformat(),
            )
        )


class TestHeartbeat:
    def test_a_run_beats_while_it_goes(self, client, monkeypatch):
        beats = []
        real = _Runs.beat
        monkeypatch.setattr(_Indexer, "HEARTBEAT_SECONDS", 0.02)
        monkeypatch.setattr(_Runs, "beat", staticmethod(lambda s, r: (beats.append(r), real(s, r))))
        original = _Indexer._process

        def slow(self, row_id, retries):
            time.sleep(0.3)
            return original(self, row_id, retries)

        monkeypatch.setattr(_Indexer, "_process", slow)
        client.index.run()
        assert len(beats) >= 3

    def test_a_new_run_starts_with_a_heartbeat(self, client):
        run = client.index.run()
        with client._db().session() as session:  # noqa: SLF001
            assert _Runs.get(session, run.id).heartbeat_at

    def test_a_quiet_live_run_is_stalled_and_a_beating_one_is_not(self, client):
        with client._db().session() as session:  # noqa: SLF001
            run = _Runs.begin(session, None, None, 1)
            run_id = run.id
        try:
            assert client.index.status().stalled is False
            old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
            with client._db().session() as session:  # noqa: SLF001
                _Runs.get(session, run_id).heartbeat_at = old
            status = client.index.status()
            assert status.active and status.stalled and status.heartbeat_at == old
            assert status.to_dict()["stalled"] is True
        finally:
            _Runs.end(run_id)

    def test_a_finished_run_is_never_stalled(self, client):
        client.index.run()
        status = client.index.status()
        assert not status.stalled and status.heartbeat_at is None


class TestIntegrityAfterALeftBehindRun:
    def test_it_is_checked_before_the_run_starts_and_a_clean_database_goes_on(
        self, client, monkeypatch
    ):
        checks = []
        real = _IntegrityCheck.run
        monkeypatch.setattr(
            _IntegrityCheck,
            "run",
            staticmethod(lambda *a, **k: (checks.append(1), real(*a, **k))[1]),
        )
        leave_a_run(client)
        assert client.index.run().status is IndexRunStatus.COMPLETED
        assert checks == [1]

    def test_a_damaged_database_stops_the_run_before_it_changes_anything(self, client, monkeypatch):
        bad = IntegrityCheckResult(False, ("page 7: bad",), datetime.now(UTC))
        monkeypatch.setattr(_IntegrityCheck, "run", staticmethod(lambda *a, **k: bad))
        leave_a_run(client)
        with pytest.raises(errors.DatabaseIntegrityError) as caught:
            client.index.run()
        assert isinstance(caught.value, errors.CorruptDatabaseError)
        assert not [r for r in client.index.history() if r.status is IndexRunStatus.COMPLETED]

    def test_an_ordinary_run_is_not_checked(self, client, monkeypatch):
        def fail(*a, **k):
            raise AssertionError("no check expected")

        monkeypatch.setattr(_IntegrityCheck, "run", staticmethod(fail))
        assert client.index.run().status is IndexRunStatus.COMPLETED

    def test_with_the_stale_lock_disabled_the_start_is_refused_not_checked(
        self, client, monkeypatch
    ):
        client.settings.index.set_stale_lock("disable")
        monkeypatch.setattr(
            _IntegrityCheck, "run", staticmethod(lambda *a, **k: pytest.fail("no check expected"))
        )
        leave_a_run(client)
        with pytest.raises(errors.IndexAlreadyRunningError, match="left behind"):
            client.index.run()


class TestSearchRebuild:
    def test_it_reports_what_it_did(self, client):
        client.index.run()
        result = client.search.rebuild()
        assert isinstance(result, SearchIndexRebuildResult)
        assert result.ok and result.pages == 1 and result.error is None
        assert result.to_dict()["pages"] == 1 and '"ok": true' in result.to_json()

    def test_it_refuses_while_an_index_run_is_going(self, client):
        with client._db().session() as session:  # noqa: SLF001
            run_id = _Runs.begin(session, None, None, 1).id
        try:
            with pytest.raises(errors.IndexAlreadyRunningError, match="rebuilt now"):
                client.search.rebuild()
        finally:
            _Runs.end(run_id)

    def test_it_rebuilds_after_a_run_was_left_behind(self, client):
        client.index.run()
        leave_a_run(client)
        assert client.search.rebuild().ok

    def test_a_failure_is_reported_not_raised(self, client, monkeypatch):
        client.index.run()

        def boom():
            raise RuntimeError("fts5 is broken")

        monkeypatch.setattr(client._search_indexer(), "rebuild", boom)  # noqa: SLF001
        result = client.search.rebuild()
        assert not result.ok and "fts5 is broken" in result.error and result.pages == 0
